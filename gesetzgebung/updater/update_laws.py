import datetime
import time
from io import BytesIO
from typing import Type

import requests
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.io import DocumentStream
from pypdfium2 import PdfDocument
from sqlalchemy import inspect
from sqlalchemy.orm import defer

from gesetzgebung.infrastructure.elasticsearch import update_law_in_es
from gesetzgebung.infrastructure.logger import log_indent
from gesetzgebung.infrastructure.config import db
from gesetzgebung.infrastructure.models import (
    Beschlussfassung,
    Dokument,
    Fundstelle,
    GesetzesVorhaben,
    Inkrafttreten,
    NewsUpdateCandidate,
    Ueberweisung,
    Verkuendung,
    Vorgangsposition,
    get_last_update,
    get_law_by_dip_id,
    get_position_by_dip_id,
    set_last_update,
)
from gesetzgebung.updater.logger import logger
from gesetzgebung.updater.pdf_mapper import (
    get_pdf,
    map_pdf_with_destinations,
    map_pdf_without_destinations,
)

DIP_API_KEY = "OSOegLs.PR2lwJ1dwCeje9vTj7FPOt3hvpYKtwKkhw"  # not an oversight, this API key is public
headers = {"Authorization": "ApiKey " + DIP_API_KEY}
DIP_ENDPOINT_VORGANGLISTE = "https://search.dip.bundestag.de/api/v1/vorgang"
DIP_ENDPOINT_VORGANGSPOSITIONENLISTE = "https://search.dip.bundestag.de/api/v1/vorgangsposition"
DIP_ENDPOINT_VORGANG = "https://search.dip.bundestag.de/api/v1/vorgang/"
DIP_ENDPOINT_VORGANGSPOSITION = "https://search.dip.bundestag.de/api/v1/vorgangsposition/"
FIRST_DATE_TO_CHECK = "2021-10-26"
LAST_DATE_TO_CHECK = datetime.datetime.now().strftime("%Y-%m-%d")

pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = True
pipeline_options.do_table_structure = True
pipeline_options.table_structure_options.do_cell_matching = True

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options, backend=PyPdfiumDocumentBackend)
    }
)


def update_laws() -> None:
    """Function to update laws from DIP. Sits at the root of the DIP update hierarchy and should be launched first with app.app_context() if __name__ == __main__"""

    # get new / updated laws from DIP
    params = (
        {
            "f.vorgangstyp": "Gesetzgebung",
            "f.datum.start": FIRST_DATE_TO_CHECK,
            "f.aktualisiert.start": last_update,
        }
        if (last_update := get_last_update())
        else {
            "f.vorgangstyp": "Gesetzgebung",
            "f.datum.start": FIRST_DATE_TO_CHECK,
            "f.datum.end": LAST_DATE_TO_CHECK,
        }
    )

    cursor = ""
    response = requests.get(DIP_ENDPOINT_VORGANGLISTE, params=params, headers=headers)
    logger.info("Starting laws update")

    while response.ok and cursor != response.json().get("cursor", None):
        response_data = response.json()
        for item in response_data.get("documents", []):
            dip_id = item.get("id", None)
            logger.debug(f"Proccesing law with dip id: {dip_id}, title: {item.get('titel', None)}")
            if law := get_law_by_dip_id(dip_id):
                logger.debug(f"A law with this dip id already exists in the database with internal id: {law.id}")
            else:
                law = GesetzesVorhaben()
                db.session.add(law)
                logger.info(
                    f"This law does not yet exist in the database. Creating new entry with dip id {dip_id}, titel: {item.get('titel', None)}."
                )

            # if not law.aktualisiert or law.aktualisiert != item.get("aktualisiert", None):
            law.dip_id = item.get("id", None)
            law.abstract = item.get("abstract", None)
            if not law.beratungsstand or law.beratungsstand[-1] != item.get("beratungsstand", None):
                law.beratungsstand.append(item.get("beratungsstand", None))
            law.sachgebiet = item.get("sachgebiet", []).copy()
            law.wahlperiode = int(item.get("wahlperiode", 0))
            law.zustimmungsbeduerftigkeit = item.get("zustimmungsbeduerftigkeit", []).copy()
            law.initiative = item.get("initiative", []).copy()
            law.aktualisiert = item.get("aktualisiert", None)
            law.titel = item.get("titel", None)
            law.datum = item.get("datum", None)

            if law_is_too_old(law):
                db.session.rollback()
                continue
            else:
                db.session.commit()

            update_positionen(law)

            verkuendung = item.get("verkuendung", [])
            update_without_dip_id(Verkuendung, law, verkuendung)

            inkrafttreten = item.get("inkrafttreten", [])
            update_without_dip_id(Inkrafttreten, law, inkrafttreten)

            db.session.commit()

            update_law_in_es(law)

            logger.debug(f"Entered into database: law dip id: {law.dip_id}, law id: {law.id}")

            time.sleep(1)

        params["cursor"] = cursor = response_data.get("cursor", None)
        response = requests.get(DIP_ENDPOINT_VORGANGLISTE, params=params, headers=headers)

    logger.info("Finished updating laws.")
    set_last_update(datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))


@log_indent
def update_positionen(law: GesetzesVorhaben) -> None:
    """Creates/Updates Vorgangspositionen for a law, as well as children of Vorgangspositionen (i.e. Ueberweisung, Fundstelle, Beschlussfassung, Dokument, NewsUpdateCandidate)."""

    # get a list of the dates of existing Vorgangspositionen for this law that already have a NewsUpdateCandidate, to prevent adding several NewsUpdateCandidates on the same date further down
    news_update_dates = (
        db.session.execute(
            (
                db.select(Vorgangsposition.datum).join(
                    NewsUpdateCandidate,
                    NewsUpdateCandidate.positions_id == Vorgangsposition.id,
                )
            ).where(Vorgangsposition.vorgangs_id == law.id)
        )
        .scalars()
        .all()
    )

    # iterate through Vorgangspositionen and associated tables
    params = {"f.vorgang": law.dip_id}
    cursor = ""
    response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)
    while response.ok and cursor != response.json().get("cursor", None):
        response_data = response.json()
        for item in response_data.get("documents", []):
            dip_id = item.get("id", None)
            logger.debug(f"Processing Vorgangsposition: {item.get('vorgangsposition', None)} with dip id: {dip_id}")

            if (position := get_position_by_dip_id(dip_id)) is None:
                logger.info(
                    f"Vorgangsposition: {item.get('vorgangsposition', None)} does not yet exist in the database. Creating new database entry with dip id: {dip_id}."
                )
                new_newsworthy_position = item.get("gang", False)
                position = Vorgangsposition()
                db.session.add(position)
            else:
                logger.debug(
                    f"Vorgangsposition with dip id: {dip_id} already present in the database under internal id: {position.id}, may update values though."
                )
                new_newsworthy_position = False

            if not position.aktualisiert or position.aktualisiert != item.get(
                "aktualisiert", None
            ):  # may wanna check item.get("gang", False) here
                position.dip_id = item.get("id", None)
                position.vorgangsposition = item.get("vorgangsposition", None)
                position.zuordnung = item.get("zuordnung", None)
                position.gang = item.get("gang", None)
                position.fortsetzung = item.get("fortsetzung", None)
                position.nachtrag = item.get("nachtrag", None)
                position.dokumentart = item.get("dokumentart", None)
                urheber = item.get("urheber", [])
                position.urheber_titel = [urh.get("titel", None) for urh in urheber]
                position.abstract = item.get("abstract", None)
                position.datum = item.get("datum", None)
                position.aktualisiert = item.get("aktualisiert", None)

                position.gesetz = law
                db.session.commit()

                ueberweisungen = item.get("ueberweisung", [])
                update_without_dip_id(Ueberweisung, position, ueberweisungen)

                fundstelle = item.get("fundstelle", {})
                update_fundstelle(position, fundstelle)

                beschlussfassungen = item.get("beschlussfassung", [])
                update_without_dip_id(Beschlussfassung, position, beschlussfassungen)

                # if the position has been newly added, has gang=True, and no other new positions have already been added for the same day, add it to the queue of NewsUpdateCandidates
                if new_newsworthy_position and position.datum not in news_update_dates:
                    news_update_dates.append(position.datum)
                    news_update_candidate = NewsUpdateCandidate()
                    news_update_candidate.position = position
                    news_update_candidate.update_count = 0
                    news_update_candidate.last_update = None
                    news_update_candidate.next_update = None
                    db.session.add(news_update_candidate)
                    db.session.commit()
                    logger.info(
                        f"Added NewsUpdateCandidate with id: {news_update_candidate.id} for Vorgangsposition with id: {position.id}"
                    )

        time.sleep(1)
        params["cursor"] = cursor = response_data.get("cursor", None)
        response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)


@log_indent
def update_fundstelle(position: Vorgangsposition, new_fundstelle: dict) -> None:
    """Creates/updates the Fundstelle of a given Vorgangsposition. Also creates new fields anfangsseite_mapped, endseite_mapped and mapped_pdf_url."""

    if (
        fundstelle := db.session.query(Fundstelle).filter(Fundstelle.positions_id == position.id).one_or_none()
    ) is None:
        logger.info(
            f"Fundstelle with dip id {new_fundstelle.get('id', None)} does not yet exist in the database. Creating new database entry."
        )
        fundstelle = Fundstelle()
        db.session.add(fundstelle)
    else:
        logger.debug(
            f"Fundstelle with dip id: {fundstelle.dip_id} already present in the database under internal id {fundstelle.id}, may update values though."
        )
        # TODO: check for any remaining errors with this:
        """select v.id, v.dip_id, v.datum, v.aktualisiert, v.titel, p.vorgangsposition, p.dip_id, p.datum, p.aktualisiert, f.id, f.dip_id, f.anfangsseite, f.pdf_url, f.anfangsseite, f.endseite, f.anfangsseite_mapped, f.endseite_mapped, d.markdown from vorhaben v
        join positionen p on p.vorgangs_id = v.id
        join fundstellen f on f.positions_id = p.id
        left join dokumente d on d.fundstelle_id = f.id
        where p.dokumentart = 'Plenarprotokoll'
        and f.anfangsseite is null
        order by v.aktualisiert desc"""
        # fix with:
        # if new_fundstelle.get("anfangsseite") and not fundstelle.anfangsseite_mapped:
        #     if (dokument := db.session.query(Dokument).filter(Dokument.fundstelle_id == fundstelle.id).one_or_none()):
        #         db.session.delete(dokument)

    fundstelle.dip_id = new_fundstelle.get("id", None)
    fundstelle.dokumentnummer = new_fundstelle.get("dokumentnummer", None)
    fundstelle.drucksachetyp = new_fundstelle.get("drucksachetyp", None)
    fundstelle.herausgeber = new_fundstelle.get("herausgeber", None)
    fundstelle.pdf_url = new_fundstelle.get("pdf_url", None)
    fundstelle.urheber = new_fundstelle.get("urheber", []).copy()
    fundstelle.anfangsseite = new_fundstelle.get("anfangsseite", None)
    fundstelle.endseite = new_fundstelle.get("endseite", None)
    fundstelle.anfangsquadrant = new_fundstelle.get("anfangsquadrant", None)
    fundstelle.endquadrant = new_fundstelle.get("endquadrant", None)
    fundstelle.position = position
    db.session.commit()

    fundstelle_infos = (
        f"Fundstelle with internal id: {fundstelle.id}, dip id: {fundstelle.dip_id}, url: {fundstelle.pdf_url}"
    )

    # We need to download the pdf if we need to map the anfangsseite/endseite and/or if we need to update the dokument.
    # Specifically, a pypdfium2.PdfDocument is needed for page mapping, and the raw pdf_content is needed for update_dokument.
    # Initiate both here so we don't have to do it in multiple places.
    pdf, pdf_content = None, None
    dokument_exists = db.session.query(
        db.session.query(Dokument).filter(Dokument.fundstelle_id == fundstelle.id).exists()
    ).scalar()
    if (fundstelle.anfangsseite and fundstelle.endseite and not fundstelle.anfangsseite_mapped) or not dokument_exists:
        pdf, pdf_content = get_pdf(fundstelle)
        if pdf is None or pdf_content is None:
            logger.warning(f"Could not download pdf for {fundstelle_infos}")
            return

    # If the fundstelle has a anfangsseite/ endseite (typically the case for BT / BR Plenarprotokolle), map them
    if fundstelle.anfangsseite and fundstelle.endseite and not fundstelle.anfangsseite_mapped:
        if fundstelle.herausgeber == "BR":
            try:
                offset = map_pdf_without_destinations(fundstelle, pdf)
                anfangsseite = fundstelle.anfangsseite - offset
                endseite = fundstelle.endseite - offset
                fundstelle.mapped_pdf_url = fundstelle.pdf_url.replace(
                    f"#P.{fundstelle.anfangsseite}", f"#page={anfangsseite}"
                )
            except Exception as e:
                logger.critical(
                    f"Error mapping destinations to pages for {fundstelle_infos}. Error: {e}",
                    subject="Error mapping destinations to pages",
                )
        elif fundstelle.herausgeber == "BT":
            try:
                destinations = map_pdf_with_destinations(fundstelle, pdf)
                anfangsseite = int(destinations[f"P.{fundstelle.anfangsseite}"])
                endseite = int(destinations[f"P.{fundstelle.endseite}"])
                fundstelle.mapped_pdf_url = fundstelle.pdf_url.replace(
                    f"#P.{fundstelle.anfangsseite}", f"#page={anfangsseite}"
                )
            except Exception as e:
                logger.critical(
                    f"Error mapping destinations to pages for {fundstelle_infos}. Error: {e}",
                    subject="Error mapping destinations to pages",
                )
        else:
            logger.critical(
                f"Invalid Herausgeber {fundstelle.herausgeber} for {fundstelle_infos}.",
                subject="Error mapping destinations to pages",
            )

        fundstelle.anfangsseite_mapped = anfangsseite
        fundstelle.endseite_mapped = endseite
        logger.info(
            f"Mapped pages and pdf_url for {fundstelle_infos}, Herausgeber: {fundstelle.herausgeber}, anfangsseite: {fundstelle.anfangsseite}, endseite: {fundstelle.endseite}, mapped anfangsseite: {fundstelle.anfangsseite_mapped}, mapped endseite: {fundstelle.endseite_mapped}"
        )

    if not dokument_exists:
        update_dokument(position, fundstelle, pdf, pdf_content)

    if pdf is not None:
        pdf.close()


@log_indent
def update_dokument(
    position: Vorgangsposition,
    fundstelle: Fundstelle,
    pdf: PdfDocument,
    pdf_content: bytes,
) -> None:
    """Converts the pdf of a given Fundstelle to markdown and stores it as a Dokument."""

    fundstelle_infos = (
        f"Fundstelle with internal id: {fundstelle.id}, dip id: {fundstelle.dip_id}, url {fundstelle.pdf_url}"
    )

    # TODO: Devise some way to process longer pdfs, e.g. splitting into smaller files.
    if len(pdf) > 500:
        logger.warning(f"Skipping {fundstelle_infos} because it has more than 500 pages.")
        return

    # create DocumentStream from raw pdf data so we don't have to load the pdf again
    doc_stream = DocumentStream(name=fundstelle.pdf_url, stream=BytesIO(pdf_content))

    if fundstelle.anfangsseite_mapped and fundstelle.endseite_mapped:
        # make below >= to include cases where anfangsseite and endseite are on the same page, but those are usually not interesting
        if fundstelle.endseite_mapped > fundstelle.anfangsseite_mapped:
            markdown = (
                converter.convert(
                    doc_stream,
                    page_range=(
                        fundstelle.anfangsseite_mapped,
                        fundstelle.endseite_mapped,
                    ),
                )
                .document.export_to_markdown()
                .replace(" ", "-")
                .replace("  ", " ")
            )
        else:
            logger.debug(
                f"Not adding Dokument for {fundstelle_infos}, because its anfangsseite and endseite are identical."
            )
            return
    else:
        markdown = converter.convert(doc_stream).document.export_to_markdown().replace(" ", "-").replace("  ", " ")

    # have to do a test query against the db because above conversion may take so long that the connection gets dropped
    try:
        db.session.query(Vorgangsposition).first()
    except Exception as e:
        logger.info(f"Connection closed during pdf processing: {e}. Reconnecting...")
        db.session.rollback()
        try:
            db.session.query(Vorgangsposition).first()
        except Exception as e:
            db.session.rollback()
            db.session.close()
            db.engine.dispose()
            logger.critical(
                f"Reconnecting to the database failed after timeout during pdf processing for {fundstelle_infos}. Exiting...",
                subject="Lost database connection during pdf processing.",
            )

    dokument = Dokument()
    dokument.markdown = markdown
    dokument.pdf_url = fundstelle.pdf_url
    dokument.conversion_date = datetime.datetime.now()
    dokument.fundstelle = fundstelle
    dokument.vorgangsposition = position.vorgangsposition
    dokument.herausgeber = fundstelle.herausgeber
    dokument.anfangsseite = fundstelle.anfangsseite_mapped if fundstelle.anfangsseite_mapped else 1
    dokument.endseite = fundstelle.endseite_mapped if fundstelle.endseite_mapped else len(pdf)
    db.session.add(dokument)
    db.session.commit()
    logger.info(f"Added Dokument with internal id {dokument.id} for {fundstelle_infos}")


@log_indent
def update_without_dip_id(
    table: Type[Verkuendung] | Type[Inkrafttreten] | Type[Ueberweisung] | Type[Beschlussfassung],
    parent_table: GesetzesVorhaben | Vorgangsposition,
    new_entries: list[dict],
) -> None:
    """Creates / updates columns in tables belongigng to a given law which have no unique identifier (dip id). Previously, I used to just delete all old entries and add all new ones, but that seemed inelegant. This function now only deletes old entries not contained in the new data, and only adds  new entries not contained in the old data. Currently used for Verkuendungen, Inkrafttreten, Ueberweisungen and Beschluesse."""

    if not new_entries:
        return

    # fetch the old values and the name of the SqlAlchemy parent-relationship attribute based on table and parent_table
    if isinstance(parent_table, GesetzesVorhaben):
        old_entries = db.session.query(table).filter_by(vorgangs_id=parent_table.id).all()
        if table == Verkuendung or table == Inkrafttreten:
            parent_attr = "vorhaben"
        else:
            logger.critical(
                f"Invalid table type {table.__name__} for parent table {parent_table.__class__.__name__} with id {parent_table.id}",
                subject="Failure in crud_without_dip",
            )
    elif isinstance(parent_table, Vorgangsposition):
        old_entries = db.session.query(table).filter_by(positions_id=parent_table.id).all()
        if table == Ueberweisung or table == Beschlussfassung:
            parent_attr = "position"
        else:
            logger.critical(
                f"Invalid table type {table.__name__} for parent table {parent_table.__class__.__name__} with id {parent_table.id}",
                subject="Failure in crud_without_dip",
            )
    else:
        logger.critical(
            f"Unsupported data type for parent table: {parent_table}",
            subject="Failure in crud_without_dip",
        )

    # get names of attributes based on which table type we are modifying (sqlalchemy relationship names are excluded by default, own and foreign key attributes have to be excluded manually)
    mapper = inspect(table)
    attrs = [column.key for column in mapper.columns if column.key not in {"id", "positions_id", "vorgangs_id"}]

    # Delete old entries which are not present in the new data
    deleted_count = 0
    for old_entry in old_entries:
        if not any(
            all(getattr(old_entry, attr) == new_entry.get(attr, None) for attr in attrs) for new_entry in new_entries
        ):
            logger.info(
                f"Deleting {table.__name__} with internal id: {old_entry.id} from {parent_table.__class__.__name__} with internal id {parent_table.id}, because it is not present in current DIP response."
            )
            db.session.delete(old_entry)
            deleted_count += 1

    # Add new entries which are not present in the old data
    added_count = 0
    for new_entry in new_entries:
        if not any(
            all(getattr(old_entry, attr) == new_entry.get(attr, None) for attr in attrs) for old_entry in old_entries
        ):
            new_object = table()

            for attr in attrs:
                setattr(new_object, attr, new_entry.get(attr, None))

            setattr(new_object, parent_attr, parent_table)
            db.session.add(new_object)
            added_count += 1

    if added_count > 0 or deleted_count > 0:
        logger.info(
            f"Added {added_count} and deleted {deleted_count} {table.__name__} to {parent_table.__class__.__name__} with internal id: {parent_table.id}"
        )
        db.session.commit()


def law_is_too_old(law: GesetzesVorhaben) -> bool:
    """Helper function to check if a law actually dates from before FIRST_DATE_TO_CHECK by checking if any of its Vorgangspositionen are from before FIRST_DATE_TO_CHECK.
    This happens sometimes if there is a new development for an old law.
    Confusingly, the "datum" field of such old laws will reflect the date of the recent change, making it impossible to filter out such laws via f.datum.start in the previous step when querying DIP_ENDPOINT_VORGANGLISTE, so we have to do it manually here.
    """
    params = {"f.vorgang": law.dip_id}
    cursor = ""
    response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)
    while response.ok and cursor != response.json().get("cursor", None):
        response_data = response.json()
        for item in response_data.get("documents", []):
            positions_datum = item.get("datum", LAST_DATE_TO_CHECK)
            if positions_datum < FIRST_DATE_TO_CHECK:
                logger.warning(
                    f"Warning: Law: {law.titel} with dip id {law.dip_id} contains Vorgangsposition {item.get('vorgangsposition', None)} {f'with datum {positions_datum}' if positions_datum != LAST_DATE_TO_CHECK else 'without a valid date'}. Its Vorgangspositionen will not be processed, and the law will not be added to the database (nor will it be removed if it already existed in the database prior to this run)."
                )
                return True
        params["cursor"] = cursor = response.json().get("cursor", None)
        response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)

    return False
