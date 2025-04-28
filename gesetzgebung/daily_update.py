import requests
from dotenv import load_dotenv
import datetime
import time
import os
from gesetzgebung.models import *
from gesetzgebung.flask_file import app
from gesetzgebung.es_file import es, ES_LAWS_INDEX, update_law_in_es
from gesetzgebung.routes import parse_law
from gesetzgebung.helpers import get_structured_data_from_ai, get_text_data_from_ai
from gesetzgebung.logger import get_logger, LogIndent, log_indent
from typing import List, Optional, Type, Tuple
from dataclasses import dataclass, field

import json
from openai import OpenAI
import newspaper
from gnews import GNews
from googlenewsdecoder import gnewsdecoder
import re
from itertools import groupby

### Below stuff was experimental, not currently needed
# from langchain_docling import DoclingLoader
# from langchain_docling.loader import ExportType
# from langchain_openai.embeddings import OpenAIEmbeddings
# from langchain_community.vectorstores import SupabaseVectorStore
# from supabase.client import Client, create_client
# import tempfile
# from pathlib import Path
# supabase_url = os.environ.get("SUPABASE_URL")
# supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
# supabase: Client = create_client(supabase_url, supabase_key)
# embeddings = OpenAIEmbeddings()

# ### Below stuff is for storing PDFs in the database
# from gesetzgebung.tokenizer_wrapper import OpenAITokenizerWrapper
from docling.chunking import HybridChunker
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.pipeline_options import PdfPipelineOptions, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling_core.types.io import DocumentStream
from io import BytesIO
import pypdfium2
import pypdfium2.raw as pdfium_c
import ctypes

pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = True
pipeline_options.do_table_structure = True
pipeline_options.table_structure_options.do_cell_matching = True

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=pipeline_options, backend=PyPdfiumDocumentBackend
        )
    }
)


basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))
logger = get_logger("update_logger")

DIP_API_KEY = "I9FKdCn.hbfefNWCY336dL6x62vfwNKpoN2RZ1gp21" # not an oversight, this API key is public
DIP_ENDPOINT_VORGANGLISTE = "https://search.dip.bundestag.de/api/v1/vorgang"
DIP_ENDPOINT_VORGANG = "https://search.dip.bundestag.de/api/v1/vorgang/"
DIP_ENDPOINT_VORGANGSPOSITIONENLISTE = "https://search.dip.bundestag.de/api/v1/vorgangsposition"
DIP_ENDPOINT_VORGANGSPOSITION = "https://search.dip.bundestag.de/api/v1/vorgangsposition/"
FIRST_DATE_TO_CHECK = "2021-10-26"
LAST_DATE_TO_CHECK = datetime.datetime.now().strftime("%Y-%m-%d")

SUMMARY_LENGTH = 700
IDEAL_ARTICLE_COUNT = 5
MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY = 3
MINIMUM_ARTICLE_LENGTH = 3000
MAXIMUM_ARTICLE_LENGTH = 20000
NEWS_UPDATE_CANDIDATES_ROLLBACK_COUNT = 20
AI_API_KEY = os.environ.get("OPENROUTER_API_KEY")
AI_ENDPOINT = "https://openrouter.ai/api/v1"

NEWS_UPDATE_INTERVALS = [
    datetime.timedelta(days=1),
    datetime.timedelta(days=3),
    datetime.timedelta(days=30),
    datetime.timedelta(days=90),
    datetime.timedelta(days=180),
] + [datetime.timedelta(days=180) * i for i in range(20)]
QUERY_UPDATE_INTERVALS = [
    datetime.timedelta(days=1),
    datetime.timedelta(days=30),
    datetime.timedelta(days=180),
    datetime.timedelta(days=360),
]
headers = {"Authorization": "ApiKey " + DIP_API_KEY}
no_news_found = 0

@dataclass
class NewsInfo:
    start_event: str
    end_event: str
    artikel: List[str] = field(default_factory=list)
    article_data: List[dict] = field(default_factory=list)
    relevant_hits: int = 0
    zusammenfassung: Optional[str] = None


EVALUATE_RESULTS_SCHEMA = {
    "name": "Artikel_Schema",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "artikel": {
                "type": "array",
                "description": "Die Liste der von dir bewerteten Artikel-Überschriften",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "index": {
                            "type": "number",
                            "description": "Die Indexnummer eines Artikels",
                        },
                        "passend": {
                            "type": "number",
                            "description": "1, wenn der Artikel mit dieser Indexnummer zum Gesetz passt, andernfalls 0",
                        },
                    },
                    "required": ["index", "passend"],
                },
            }
        },
        "required": ["artikel"],
    },
}
RESULTS_SCHEMA_DUMPS = json.dumps(EVALUATE_RESULTS_SCHEMA, ensure_ascii=False, indent=4)

GENERATE_QUERIES_SCHEMA = {
    "name": "Suchanfragen_Schema",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "suchanfragen": {
                "type": "array",
                "description": "Die Liste der von dir generierten Suchanfragen",
                "items": {
                    "type": "string",
                    "description": "Eine von dir generierte Suchanfrage",
                },
            }
        },
        "required": ["suchanfragen"],
    },
}
QUERIES_SCHEMA_DUMPS = json.dumps(GENERATE_QUERIES_SCHEMA, ensure_ascii=False, indent=4)

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
            logger.debug(f"Proccesing law with dip id: {dip_id}, title: {item.get("titel", None)}")
            if (law := get_law_by_dip_id(dip_id)):
                logger.debug(f"A law with this dip id already exists in the database with internal id: {law.id}")
            else:
                law = GesetzesVorhaben()
                db.session.add(law)
                logger.info(f"This law does not yet exist in the database. Creating new entry with dip id {dip_id}, titel: {item.get("titel", None)}.")

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

            logger.debug(f"Entered into database: law dip id: {law.dip_id}, law dip id type: {type(law.dip_id)}, law id: {law.id}")

            time.sleep(1)

        params["cursor"] = cursor = response_data.get("cursor", None)
        response = requests.get(DIP_ENDPOINT_VORGANGLISTE, params=params, headers=headers)

    logger.info("Finished updating laws.")
    set_last_update(datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))


def update_news_update_candidates() -> None:
    """Function to update NewsUpdateCandidates. Sits at the root of the news update hierarchy and should be launched after update_laws() with app.app_context() if __name__ == __main__.
    Process for updating news articles / creating summaries:
    - This is a bit more complex than might seem necessary, because it needs to also work when first populating the database.
    - Check all NewsUpdateCandidates (i.e. Vorgangspositionen that haven't had a news summary added in a while, or at all)
    - If a NewsUpdateCandidate is new, it receives its first update, any older NewsUpdateCandidates belonging to the same law receive their final update and are removed from the list
    - If no new NewsUpdateCandidates were added for a given law, existing ones get updated periodically in increasing intervals
    - Updating means that news articles for the relevant timeframe will be searched, and a summary will be created if enough (new) articles are found."""

    client = OpenAI(base_url=AI_ENDPOINT, api_key=AI_API_KEY)
    gn = GNews(language="de", country="DE")
    now = datetime.datetime.now().date()

    # create a candidate_groups list of dicts that have law ids as keys, and a list of NewsUpdateCandidates corresponding to that law id, in reverse chronological order, as values (if this runs daily, there should only be 1-2 NewsUpdateCandidate per law, but there will be many when first populating the database). We need not worry about several NewsUpdateCandidates of a given law being on the same date, as this is prevented in update_positionen when adding NewsUpdateCandidates
    all_candidates = db.session.query(NewsUpdateCandidate).join(Vorgangsposition).join(GesetzesVorhaben).order_by(GesetzesVorhaben.id, Vorgangsposition.datum).all()
    candidate_groups = {law_id: sorted(list(group), key=lambda c: c.position.datum, reverse=True) for law_id, group in groupby(all_candidates, key=lambda c: c.position.gesetz.id)}

    # as we crud the NewsUpdateCandidates, we need to save X amount of them in case we ever need to roll back after discovering that gnews has been blocking us.
    saved_for_rollback = []

    for law_id, candidates in candidate_groups.items():
        logger.info(f"*** Starting news update for law with id {law_id}, update candidate ids: {[c.id for c in candidates]} ***")
        law = get_law_by_id(law_id)
        
        # we use the parse_law function with display=False from the webapp here to get some more info to later feed to the llm about the Vorgangspositionen that mark the start and end of a given timespan.
        infos = parse_law(law, display=False)

        # The function for summarizing news articles informs the LLM about the Vorgangspositionen after / before which the news articles have been published. Since there is no Vorgangsposition after the most recent one, we create a dummy node to cover this time period.  
        completion_state = "Das Ereignis, das den Start dieses Zeitraums markiert, markiert zugleich den erfolgreichen Abschluss des Gesetzgebungsverfahrens." if any(
            info["marks_success"] for info in infos) else "Das Ereignis, das den Start dieses Zeitraums markiert, markiert zugleich das Scheitern des Gesetzgebungsverfahrens." if any(
            info["marks_failure"] for info in infos) else "Das Ereignis, das den Start dieses Zeitraums markiert, ist das momentan aktuellste im laufenden Gesetzgebungsverfahren."
        dummy_info = {
            "datetime": now,
            "ai_info": f"{completion_state} Die mit diesem Zeitraum verknüpften Nachrichtenartikel reichen somit bis zum heutigen Tag.",
        }

        # There is a sublist of NewsUpdateCandidates for each law saved for rollback. If we can pop the first of these sublists, and have the items of the remaining sublists be > the number of times gnews returned 0, popping the first sublist is safe to do.
        if sum(len(candidates_of_a_given_law) for candidates_of_a_given_law in saved_for_rollback[1:]) > no_news_found:
            saved_for_rollback.pop(0)

        # New NewsUpdateCandidate sublist for new law
        saved_for_rollback.append([])

        # work through NewsUpdateCandidates of a law, starting with the most recent. Get info for it and for the next one up (= dummy info in case of most recent NewsUpdateCandidate)
        for i, candidate in enumerate(candidates):
            position = candidate.position
            info = next(inf for inf in infos if inf["id"] == position.id)  
            next_info = next(inf for inf in infos if inf["id"] == candidates[i - 1].position.id) if i > 0 else dummy_info

            # skip if candidate has already been updated and is not due for its next update
            if candidate.next_update and candidate.next_update > now:
                continue

            # otherwise, save for rollback, as changes are about to be made
            saved_for_rollback[-1].append(SavedNewsUpdateCandidate(candidate))
            
            # remove below condition to update a law's search queries within defined intervals instead of just once. Might make sense if the llm is periodically upgraded to a newer model with up-to-date training data and/or web search abilities that would allow it to catch new ways that a law is being referred to in common parlance. Still undecided about this.
            if not law.queries: 
                update_queries(client, law, now)

            # update news articles for this candidate
            update_news(
                client,
                gn,
                position,
                [info] + [next_info],
                saved_for_rollback,
                law,
            )

            # Delete all but the most recent NewsUpdateCandidate, as nothing new is going to happen within the timeframes that they represent
            if i > 0:
                db.session.delete(candidate)
            else:
                candidate.last_update = now
                # Schedule the next update based on the position's age. We can't just do candidate.next_update = (now + NEWS_UPDATE_INTERVALS[min(len(NEWS_UPDATE_INTERVALS) - 1, candidate.update_count)]), as that would work fine on new positions, but schedule the next update for historical positions too early. 
                position_age = now - position.datum
                next_interval = next((interval for interval in NEWS_UPDATE_INTERVALS if interval > position_age), 
                                    NEWS_UPDATE_INTERVALS[-1])
                candidate.next_update = now + next_interval
                candidate.update_count += 1
            db.session.commit()

@log_indent
def update_queries(client : OpenAI, law : GesetzesVorhaben, now : datetime.date) -> None:
    """Wrapper around generate_search_queries, which checks if the next update is due and assigns the new queries to the law if so"""
    last_updated = law.queries_last_updated or datetime.date(1900, 1, 1)
    if now - last_updated > QUERY_UPDATE_INTERVALS[min(law.query_update_counter, len(QUERY_UPDATE_INTERVALS) - 1)]:
        law.queries = generate_search_queries(client, law)
        if law.queries:
            law.queries_last_updated = now
            law.query_update_counter += 1
        else:
            logger.critical(f"CRITICAL: No search queries available for law with id {law.id}, terminating.", 
                                    subject="Could not generate search queries.")

@log_indent
def update_news(client : OpenAI, gn : GNews, position : Vorgangsposition, infos : list[dict], saved_for_rollback : list[SavedNewsUpdateCandidate], law : GesetzesVorhaben) -> None:
    """Wrapper function around get_news and generate_summary, which cruds the NewsSummary and NewsArticle objects"""
    
    # get news articles and summary
    news_info = get_news(client, gn, position, infos, saved_for_rollback, law)
    news_info = generate_summary(client, news_info, position, law)

    # if no summary was created, do nothing (conveniently, this means no changes get made, except those to the NewsUpdateCandidates themselves, if gnews ever becomes unresponsive)
    if not news_info.zusammenfassung:
        return

    # if a summary already exists, delete it and the articles associated with it
    if position.summary:
        for article in position.summary.articles:
            db.session.delete(article)
        db.session.delete(position.summary)

    # create new summary
    summary = NewsSummary()
    summary.summary = news_info.zusammenfassung
    summary.articles_found = news_info.relevant_hits
    summary.position = position
    db.session.add(summary)

    # create new articles
    for article in news_info.article_data:
        a = NewsArticle()
        a.description = article.get("description", "")
        a.publisher = article.get("publisher", {}).get("title", "")
        a.published_date = article.get("published date", None)
        a.title = article.get("title", "")
        a.url = article.get("url", "")
        a.summary = summary
        db.session.add(a)
    db.session.commit()

@log_indent
def update_without_dip_id(table : Type[Verkuendung] | Type[Inkrafttreten] | Type[Ueberweisung] | Type[Beschlussfassung], parent_table : GesetzesVorhaben | Vorgangsposition, new_entries: list[dict]) -> None:
    """Creates / updates columns in tables belongigng to a given law which have no unique identifier (dip id). Previously, I used to just delete all old entries and add all new ones, but that seemed inelegant. This function now only deletes old entries not contained in the new data, and only adds  new entries not contained in the old data. Currently used for Verkuendungen, Inkrafttreten, Ueberweisungen and Beschluesse."""

    if not new_entries:
        return
    
    # fetch the old values and the name of the SqlAlchemy parent-relationship attribute based on table and parent_table
    if isinstance(parent_table, GesetzesVorhaben):
        old_entries = db.session.query(table).filter_by(vorgangs_id=parent_table.id).all()
        if table == Verkuendung or table == Inkrafttreten:
            parent_attr = "vorhaben"
        else:
            logger.critical(f"Invalid table type {table.__name__} for parent table {parent_table.__class__.__name__} with id {parent_table.id}", subject="Failure in crud_without_dip")
    elif isinstance(parent_table, Vorgangsposition):
        old_entries = db.session.query(table).filter_by(positions_id=parent_table.id).all()
        if table == Ueberweisung or table == Beschlussfassung:
            parent_attr = "position"
        else:
            logger.critical(f"Invalid table type {table.__name__} for parent table {parent_table.__class__.__name__} with id {parent_table.id}", subject="Failure in crud_without_dip")
    else:
        logger.critical(f"Unsupported data type for parent table: {parent_table}", subject="Failure in crud_without_dip")
    
    # get names of attributes based on which table type we are modifying (sqlalchemy relationship names are excluded by default, own and foreign key attributes have to be excluded manually)
    mapper = inspect(table)
    attrs = [column.key for column in mapper.columns if column.key not in {"id", "positions_id", "vorgangs_id"}]
    
    # Delete old entries which are not present in the new data
    deleted_count = 0
    for old_entry in old_entries:
        if not any(
            all(getattr(old_entry, attr) == new_entry.get(attr, None) for attr in attrs) 
            for new_entry in new_entries
        ):
            logger.info(f"Deleting {table.__name__} with internal id: {old_entry.id} from {parent_table.__class__.__name__} with internal id {parent_table.id}, because it is not present in current DIP response.")
            db.session.delete(old_entry)
            deleted_count += 1
    
    # Add new entries which are not present in the old data
    added_count = 0
    for new_entry in new_entries:
        if not any(
            all(getattr(old_entry, attr) == new_entry.get(attr, None) for attr in attrs)
            for old_entry in old_entries
        ):
            new_object = table()
            
            for attr in attrs:
                setattr(new_object, attr, new_entry.get(attr, None))
            
            setattr(new_object, parent_attr, parent_table)
            db.session.add(new_object)
            added_count += 1

    if added_count > 0 or deleted_count > 0:
        logger.info(f"Added {added_count} and deleted {deleted_count} {table.__name__} to {parent_table.__class__.__name__} with internal id: {parent_table.id}")
        db.session.commit()

def law_is_too_old(law : GesetzesVorhaben) -> bool:
    """Helper function to check if a law actually dates from before FIRST_DATE_TO_CHECK by checking if any of its Vorgangspositionen are from before FIRST_DATE_TO_CHECK. 
    This happens sometimes if there is a new development for an old law. 
    Confusingly, the "datum" field of such old laws will reflect the date of the recent change, making it impossible to filter out such laws via f.datum.start in the previous step when querying DIP_ENDPOINT_VORGANGLISTE, so we have to do it manually here.""" 
    params = {"f.vorgang": law.dip_id}
    cursor = ""
    response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)
    while response.ok and cursor != response.json().get("cursor", None):
        response_data = response.json()
        for item in response_data.get("documents", []):
            positions_datum = item.get("datum", LAST_DATE_TO_CHECK)
            if positions_datum < FIRST_DATE_TO_CHECK:
                logger.warning(f"Warning: Law: {law.titel} with dip id {law.dip_id} contains Vorgangsposition {item.get("vorgangsposition", None)} {f'with datum {positions_datum}' if positions_datum != LAST_DATE_TO_CHECK else "without a valid date"}. Its Vorgangspositionen will not be processed, and the law will not be added to the database (nor will it be removed if it already existed in the database prior to this run).")
                return True
        params["cursor"] = cursor = response.json().get("cursor", None)
        response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)

    return False

@log_indent
def update_positionen(law : GesetzesVorhaben) -> None:
    """Creates/Updates Vorgangspositionen for a law, as well as children of Vorgangspositionen (i.e. Ueberweisung, Fundstelle, Beschlussfassung, Dokument, NewsUpdateCandidate)."""

    # get a list of the dates of existing Vorgangspositionen for this law that already have a NewsUpdateCandidate, to prevent adding several NewsUpdateCandidates on the same date further down
    news_update_dates = (
        db.session.execute(
        (db.select(Vorgangsposition.datum)
        .join(NewsUpdateCandidate, NewsUpdateCandidate.positions_id == Vorgangsposition.id))
        .where(Vorgangsposition.vorgangs_id == law.id)
    )
    .scalars()
    .all())

    # iterate through Vorgangspositionen and associated tables
    params = {"f.vorgang": law.dip_id}
    cursor = ""
    response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)
    while response.ok and cursor != response.json().get("cursor", None):
        response_data = response.json()
        for item in response_data.get("documents", []):
            dip_id = item.get("id", None)
            logger.debug(f"Processing Vorgangsposition: {item.get("vorgangsposition", None)} with dip id: {dip_id}")

            if (position := get_position_by_dip_id(dip_id)) is None:
                logger.info(f"Vorgangsposition: {item.get("vorgangsposition", None)} does not yet exist in the database. Creating new database entry with dip id: {dip_id}.")
                new_newsworthy_position = item.get("gang", False)
                position = Vorgangsposition()
                db.session.add(position)
            else:
                logger.debug(f"Vorgangsposition with dip id: {dip_id} already present in the database under internal id: {position.id}, may update values though.")
                new_newsworthy_position = False
            
            if not position.aktualisiert or position.aktualisiert != item.get("aktualisiert", None):  # may wanna check item.get("gang", False) here
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
                    logger.info(f"Added NewsUpdateCandidate with id: {news_update_candidate.id} for Vorgangsposition with id: {position.id}")

        time.sleep(1)
        params["cursor"] = cursor = response_data.get("cursor", None)
        response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)

def get_pdf(fundstelle: Fundstelle) -> Tuple[pypdfium2.PdfDocument, requests.Response.content]:
    """Helper function to download a pdf (used for mapping pages / converting to markdown). Returns a tuple of the pypdfium2 PdfDocument, and the raw response content"""
    try:
        with requests.get(fundstelle.pdf_url) as response:
            response.raise_for_status()
            pdf_content = response.content
            pdf = pypdfium2.PdfDocument(pdf_content)
            return pdf, pdf_content

    except Exception as e:
        logger.critical(f"Error occurred on Fundstelle {fundstelle.id} with url {fundstelle.pdf_url}.\n Error: {e}",
                        subject="Error downloading pdf document from Fundstelle",
        )

@log_indent
def update_fundstelle(position: Vorgangsposition, new_fundstelle: dict) -> None:
    """Creates/updates the Fundstelle of a given Vorgangsposition. Also creates new fields anfangsseite_mapped, endseite_mapped and mapped_pdf_url."""

    if (fundstelle := db.session.query(Fundstelle).filter(Fundstelle.positions_id == position.id).one_or_none()) is None:
        logger.info(f"Fundstelle with dip id {new_fundstelle.get("id", None)} does not yet exist in the database. Creating new database entry.")
        fundstelle = Fundstelle()
        db.session.add(fundstelle)
    else:
        logger.debug(f"Fundstelle with dip id: {fundstelle.dip_id} already present in the database under internal id {fundstelle.id}, may update values though.")

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

    fundstelle_infos = f"Fundstelle with internal id: {fundstelle.id}, dip id: {fundstelle.dip_id}, url: {fundstelle.pdf_url}"

    # a pypdfium2.PdfDocument is needed for mapping of anfangsseite / endseite and update_dokument, raw pdf_content is needed for update_dokument. Initiate both here so we don't have to do it multiple times.
    pdf, pdf_content = None, None

    # If the fundstelle has a anfangsseite/ endseite (typically the case for BT / BR Plenarprotokolle), map them
    if fundstelle.anfangsseite and not fundstelle.anfangsseite_mapped:
        pdf, pdf_content = get_pdf(fundstelle)

        if fundstelle.herausgeber == "BR":
            try:
                offset = map_pdf_without_destinations(fundstelle, pdf)
                anfangsseite_internal = fundstelle.anfangsseite
                anfangsseite = int(anfangsseite_internal) - offset
                endseite = int(fundstelle.endseite) - offset
                fundstelle.mapped_pdf_url = fundstelle.pdf_url.replace(f"#P.{anfangsseite_internal}", f"#page={anfangsseite}")
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
                fundstelle.mapped_pdf_url = fundstelle.pdf_url.replace(f"#P.{anfangsseite_internal}", f"#page={anfangsseite}")
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
        logger.info(f"Mapped pages and pdf_url for {fundstelle_infos}, Herausgeber: {fundstelle.herausgeber}, anfangsseite: {fundstelle.anfangsseite}, endseite: {fundstelle.endseite}, mapped anfangsseite: {fundstelle.anfangsseite_mapped}, mapped endseite: {fundstelle.endseite_mapped}")

    fundstelle.position = position
    db.session.commit()

    if not fundstelle.dokument:
        if pdf is None or pdf_content is None:
            pdf, pdf_content = get_pdf(fundstelle)
        update_dokument(position, fundstelle, pdf, pdf_content)

    if pdf is not None:
        pdf.close()

@log_indent
def update_dokument(position: Vorgangsposition, fundstelle: Fundstelle, pdf: pypdfium2.PdfDocument, pdf_content: requests.Response.content) -> None:
    """Converts the pdf of a given Fundstelle to markdown and stores it as a Dokument."""
    
    fundstelle_infos = f"Fundstelle with internal id: {fundstelle.id}, dip id: {fundstelle.dip_id}, url {fundstelle.pdf_url}"
    
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
                    page_range=(fundstelle.anfangsseite_mapped, fundstelle.endseite_mapped),
                )
                .document.export_to_markdown()
                .replace(" ", "-")
                .replace("  ", " ")
            )
        else:
            logger.debug(f"Not adding Dokument for {fundstelle_infos}, because its anfangsseite and endseite are identical.")
            return
    else:
        markdown = converter.convert(doc_stream).document.export_to_markdown().replace(" ", "-").replace("  ", " ")

    # have to do a test query against the db because above conversion may take so long that the connection gets dropped
    try:
        test = db.session.query(Vorgangsposition).first()
    except Exception as e:
        logger.info(f"Connection closed during pdf processing: {e}. Reconnecting...")
        db.session.rollback()
        try:
            test = db.session.query(Vorgangsposition).first()
        except Exception as e:
            db.session.rollback()
            db.session.close()
            db.engine.dispose()
            logger.critical(f"Reconnecting to the database failed after timeout during pdf processing for {fundstelle_infos}. Exiting...",
                            subject="Lost database connection during pdf processing.")

    dokument = Dokument()
    dokument.markdown = markdown
    dokument.pdf_url = fundstelle.pdf_url
    dokument.conversion_date = datetime.datetime.now()
    dokument.fundstelle = fundstelle
    dokument.vorgangsposition = position.vorgangsposition
    dokument.herausgeber = fundstelle.herausgeber
    db.session.add(dokument)
    db.session.commit()
    logger.info(f"Added Dokument with internal id {dokument.id} for {fundstelle_infos}")


@log_indent
def get_news(client : OpenAI, gn : GNews, position : Vorgangsposition, infos : list[dict], saved_for_rollback : list[SavedNewsUpdateCandidate], law : GesetzesVorhaben) -> NewsInfo:
    """Finds news articles for a given Vorgangsposition and returns a NewsInfo object"""

    # prefer this over passing it around between a bunch of functions that mostly don't need it
    global no_news_found 

    start_date = infos[0]["datetime"]
    end_date = infos[1]["datetime"]
    news_info = NewsInfo(start_event=infos[0]["ai_info"], end_event=infos[1]["ai_info"])

    gn.start_date = (start_date.year, start_date.month, start_date.day)
    gn.end_date = (end_date.year, end_date.month, end_date.day)

    # get all article urls that have already been used for this law. This is needed later to avoid dupes. 
    # Otherwise, an article published on the same day as a Vorgangsposition might get included in both the summary for the timespan leading up to that Vorgangsposition, and in the summary for the timespan following that Vorgangsposition. 
    # (A better solution would be to be precise to the hour/minute/second as opposed to just the day, but this is not supported by the gnews package, nor is it even specified in Vorgangsposition.datum)
    used_article_urls = (db.session.query(NewsArticle.url)
    .join(NewsSummary, NewsArticle.summary_id == NewsSummary.id)
    .join(Vorgangsposition, NewsSummary.positions_id == Vorgangsposition.id)
    .join(GesetzesVorhaben, Vorgangsposition.vorgangs_id == GesetzesVorhaben.id)
    .filter(GesetzesVorhaben.id == law.id)
    .all())

    logger.debug(f"Retrieving news for law: {law.titel} from {news_info.start_event} ({start_date}) to {news_info.end_event} ({end_date})")

    for query_counter, query in enumerate(law.queries):
        time.sleep(1)

        # If no news have been found for a while, check if it is just a coincidence, or if gnews is blocking us
        if no_news_found >= NEWS_UPDATE_CANDIDATES_ROLLBACK_COUNT:
            consider_rollback(saved_for_rollback)

        # if there are no news for this query, continue with the next
        if not (gnews_response := gn.get_news(query)):
            no_news_found += 1
            logger.debug(f"No news found for query {query_counter+1}/{len(law.queries)}: {query}, start date: {gn.start_date}, end date: {gn.end_date}")
            continue

        no_news_found = 0
        num_found = len(gnews_response)
        logger.debug(f"found {num_found} articles for query {query_counter+1}/{len(law.queries)}: {query}, start date: {gn.start_date}, end date: {gn.end_date}")

        # use llm to check which articles are likely relevant based on their titles
        evaluate_results_messages = [
            {
                "content": f"""Du erhältst vom Nutzer eine Liste von strukturierten Daten. 
Jeder Eintrag in der Liste besteht aus einer Indexnummer und der Überschrift eines Nachrichtenartikels, die Nachricht des Nutzers wird also folgende Struktur haben: 
[{{'index': '1', 'titel': 'Ueberschrift_des_ersten_Nachrichtenartikels'}}, {{'index': '2', 'titel': 'Ueberschrift_des_zweiten_Nachrichtenartikels'}}, etc]. 
Deine Aufgabe ist es, für jeden Eintrag anhand der Überschrift zu prüfen, ob der Nachrichtenartikel sich auf das deutsche Gesetz mit dem amtlichen Titel '{law.titel}' bezieht, oder nicht. 
Dementsprechend wirst du in das Feld 'passend' in deiner Antwort entweder eine 1 (wenn der Nachrichtenartikel sich auf das Gesetz bezieht) oder eine 0 (wenn der Nachrichtenartikel sich nicht auf das Gesetz bezieht) eintragen.
Deine Antwort wird ausschließlich aus JSON Daten bestehen und folgende Struktur haben: {RESULTS_SCHEMA_DUMPS}""",
                "role": "system",
            },
            {
                "content": json.dumps(
                    [{"index": i, "titel": article.get("title", "Titel nicht verfügbar")} for i, article in enumerate(gnews_response)],
                    ensure_ascii=False,
                ),
                "role": "user",
            },
        ]
    
        # pop all irrelevant articles from gnews_response
        try:
            ai_response = get_structured_data_from_ai(client, evaluate_results_messages, EVALUATE_RESULTS_SCHEMA, "artikel")

            for i in range(len(gnews_response) - 1, -1, -1):
                if ai_response[i]["passend"] in {0, "0"}:
                    gnews_response.pop(i)

        except Exception as e:
            logger.critical(f"Error evaluating search results: {e}. Evaluate results messages: {evaluate_results_messages}, ai response: {ai_response}", subject="Error evaluating search results")
            continue

        # The current calculation of total relevant hits may skew results, because it does not account for duplicates in the search results.
        # Ideally, we'd want to just get the actual, full result count, not be limited to max. 100 results per query as is the case with gnews, but that would require manual scraping or third party apis
        # Failing that, a better approach may be to declare a set of total_relevant_hits before we loop through the queries, then do:
        # total_relevant_hits.add(relevant_hit["url"] for relevant_hit in gnews_response)
        # news_info.relevant_hits = len(total_relevant_hits)
        # However, that may also skew results, because a high duplicate count may be down to queries being more similar for one law than another, which is not necessarily indicative of the true number of relevant articles for the laws, particularly as gnews will return at most 100 results per query.
        # Another approach would be to only count relevant hits of the best query:
        # news_info.relevant_hits = max(news_info.relevant_hits, len(gnews_response))
        # That might be the way to go, but I am leaving it as is for now, because I only discovered this issue after processing 598 / 753 laws
        # If I change it now, the results for the relevant hit count for the remaining laws will be skewed as compared to the first 598
        # Leaving this comment in as a mental note in case I decide to re-process all laws at some point.

        news_info.relevant_hits += len(gnews_response)
        logger.debug(f"Eliminated {num_found - len(gnews_response)} irrelevant articles for query: {query}. {len(gnews_response)} relevant articles remain.")

        # iterate through the relevant articles
        for article in gnews_response:

            # stop if we have enough articles
            if len(news_info.artikel) >= IDEAL_ARTICLE_COUNT:
                break

            # decode the article's URL
            try:
                url = gnewsdecoder(article["url"], 3)
                if url["status"]:
                    article["url"] = url["decoded_url"]
                else:
                    logger.warning(f"Failed to decode URL {article['url']} of article {article}")
                    continue
            except Exception as e:
                logger.error(f"Unknown Error {e} while decoding URL {article['url']} of article {article}", subject="Error decoding URL")
                continue
            
            # skip the article if it has already been processed, either from another search query for the current timespan (first check) or in a different timespan pertaining to the same law (second check, see above) 
            if any(article["url"] == existing_article["url"] for existing_article in news_info.article_data) or article["url"] in used_article_urls:
                continue

            # skip the article if we cannot download / parse it
            try:
                news_article = newspaper.article(article["url"], language="de")
            except Exception as e:
                logger.info(f"Error parsing news article: {str(e)}")
                continue

            # skip the article if it is too short / long / otherwise invalid
            if not news_article.is_valid_body() or len(news_article.text) < MINIMUM_ARTICLE_LENGTH or len(news_article.text) > MAXIMUM_ARTICLE_LENGTH:
                continue

            # sometimes articles that got updated later are included in the response from Google News. This filters out some of those, though still not all.
            if not news_article.publish_date or news_article.publish_date.date() >= end_date:
                continue

            # add the article's text and associated data to our news_info object
            news_info.artikel.append(news_article.text)
            news_info.article_data.append(article)

    return news_info

@log_indent
def generate_summary(client : OpenAI, news_info : NewsInfo, position : Vorgangsposition, law : GesetzesVorhaben) -> NewsInfo:
    """Generates a summary for a given Vorgangsposition from a NewsInfo object"""

    # if we don't have enough articles, return without creating a summary
    if len(news_info.artikel) < MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY:
        logger.info(f"Only found {len(news_info.artikel)} usable articles, need {MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY} to display summary.")
        return news_info

    # if a summary already exists
    if position.summary:
        # ...don't make a new one if the old one was based on more articles
        if len(news_info.artikel) < len(position.summary.articles):
            logger.info(f"Already had a summary based on {len(position.summary.articles)} articles, only have {len(news_info.artikel)} articles now, no update to the summary is needed.")
        # ... or if the old one had a sufficient number of hits, and we don't have at least 1.5x as many
        elif position.summary.articles_found >= IDEAL_ARTICLE_COUNT and news_info.relevant_hits < position.summary.articles_found * 1.5:
            logger.info(f"Already had a summary based on {position.summary.articles_found} relevant hits, only have {news_info.relevant_hits} relevant hits now, no update to the summary is needed.")
            return news_info

    # TODO: make this less verbose
    generate_summary_messages = [
        {
            "content": f"""Du erhältst vom Nutzer Angaben zu einem Zeitraum innerhalb des Gesetzgebungsverfahrens für das deutsche Gesetz mit dem amtlichen Titel {law.titel}. 
Der Nutzer schickt dir das Ereignis, das am Anfang des Zeitraums steht, das Ereignis, das unmittelbar nach dem Ende des Zeitraums eintreten wird, und eine Liste von Nachrichtenartikeln, die innerhalb des Zeitraums erschienen sind.
Die Nachricht des Nutzers wird also folgendes Format haben:
'start': 'Die Bundesregierung bringt den Gesetzentwurf in den Bundestag ein', 'end': 'Die 1. Lesung im Bundestag findet statt.', 'artikel': ['Nachrichtenartikel 1', 'Nachrichtenartikel 2', etc]

Du musst diese Nachricht in zwei Phasen bearbeiten.
PHASE 1:
Zunächst sollst du alle Nachrichtenartikel überprüfen. Falls ein Nachrichtenartikel sich nicht auf das Gesetz bezieht, oder nicht zu dem vom Nutzer angegebenen Zeitraum passt, MUSST DU IHN IGNORIEREN.
Beachte dabei folgendes: Das Ereignis, das im Feld 'end' eines jeden Zeitabschnitts genannt wird, ist **in dem jeweiligen Zeitabschnitt noch nicht passiert**, sondern passiert erst unmittelbar nach diesem Zeitabschnitt. (Es sei denn, der Wert im Feld start markiert das vorläufige oder endgültige Ende des Gesetzgebungsverfahrens, und der Wert im Feld end markiert den heutigen Tag.)
Wenn ein Zeitabschnitt also zum Beispiel end = "Die Beratung und Abstimmung im Bundesrat finden statt" hat, und mit diesem Zeitraum ein Nachrichtenartikel verknüpft ist, in dem steht, dass die Abstimmung im Bundesrat schon stattgefunden habe, dann ist dieser Nachrichtenartikel irrtümlich in die Liste der Artikel für diesen Zeitraum geraten, und **muss beim Erstellen der Zusammenfassung für diesen Zeitraum ignoriert werden**.

PHASE 2:
Wenn du entschieden hast, ob und gegebenenfalls welche Nachrichtenartikel du ignorieren musst, sollst du eine Zusammenfassung der wichtigsten und interessantesten Inhalte der übrigen Nachrichtenartikel erstellen.
Falls einzelne Nachrichtenartikel von mehreren, unterschiedlichen Gesetzen handeln, solltest du nur diejenigen Inhalte in die Zusammenfassung aufnehmen, die sich auf das Gesetz mit dem amtlichen Titel {law.titel} beziehen.
Wichtige / interessante nachrichtliche Inhalte sind zum Beispiel: Lob und Kritik zu dem Gesetz, die politische und mediale Auseinandersetzung mit dem Gesetz, Besonderheiten des Gesetzgebungsverfahrens, Klagen gegen das Gesetz, Stellungnahmen von durch das Gesetz betroffenen Personen oder Verbänden sowie einzelne, besonders im Fokus stehende Passagen des Gesetzes. 
Weniger interessant ist hingegen eine neutrale Schilderung der wesentlichen Inhalte des Gesetzes - diese sollte in die Zusammenfassung nur aufgenommen werden, wenn sich aus den Nachrichtenartikeln nichts anderes, interessantes ergibt.            
Einleitende Formulierungen wie "Im ersten Zeitraum" oder "In diesem Zeitraum" am Anfang der Zusammenfassung sollst du vermeiden. Du sollst aber auf das Ereignis Bezug nehmen, das den Start des jeweiligen Zeitraums markiert, sofern es in den Nachrichtenartikeln eine Rolle gespielt hat. 
Die Zusammenfassung muss mindestens {SUMMARY_LENGTH - 100} und darf höchstens {SUMMARY_LENGTH + 100} Zeichen lang sein.
Deine Zusammenfassung soll im Präsens verfasst sein. 
Deine Antwort muss aus reinem, unformatiertem Text bestehen und AUSSCHLIEßLICH die Zusammenfassung enthalten. Sie darf keine weiteren Informationen enthalten, nicht einmal eine einleitende Überschrift wie zum Beispiel "Zusammenfassung:".""",
            "role": "system",
        },
        {
            "content": json.dumps(
                {
                    "start": news_info.start_event,
                    "end": news_info.end_event,
                    "artikel": news_info.artikel,
                },
                ensure_ascii=False,
            )
            .replace("\\n", "\n")
            .replace('\\"', '"'),
            "role": "user",
        },
    ]

    if not (ai_response := get_text_data_from_ai(client, generate_summary_messages)):
        logger.critical(f"""Error getting summary for news info: {generate_summary_messages[1]["content"]}""")
        return news_info

    news_info.zusammenfassung = ai_response
    logger.info(f"Generated summary for law: {law.titel} from {news_info.start_event} to {news_info.end_event} based on {len(news_info.artikel)} news articles")
    return news_info


def consider_rollback(saved_for_rollback : list[SavedNewsUpdateCandidate]) -> None:
    """Helper function to check if gnews has become unresponsive, and roll back news update candidates if so"""

    global no_news_found

    logger.debug(f"Checking if gnews is unresponsive, after receiving no news for {no_news_found} queries in a row")

    # try to get news for a test query that should yield tons of hits
    try:
        test_gn = GNews(language="de", country="DE")
        test_gn.start_date(2024, 1, 1)
        test_gn.end_date(2025, 1, 1)
        test_query = test_gn.get_news("Selbstbestimmungsgesetz")
        test_result_count = len(test_query)
    except Exception as e:
        test_result_count = 0

    # if it doesnt, try to roll back and terminate the script
    if test_result_count < 100:
        error_message = f"No news found for {no_news_found} queries in a row, test query only returned {test_result_count} results.\n"
        try:
            for candidates_of_a_given_law in saved_for_rollback:
                for original in candidates_of_a_given_law:
                    # recreate candidate if it has been deleted (forgot to do this in earlier versions, likely leading to some odd downstream behaviour)
                    if (candidate := db.session.query(NewsUpdateCandidate).filter(NewsUpdateCandidate.id == original.id).one_or_none()) is None:
                        candidate = NewsUpdateCandidate()
                        db.session.add(candidate)
                    candidate.last_update = original.last_update
                    candidate.next_update = original.next_update
                    candidate.update_count = original.update_count
                    candidate.position = original.position
            db.session.commit()
            error_message += f"Successfully rolled back {sum(len(candidates_of_a_given_law) for candidates_of_a_given_law in saved_for_rollback)} news update candidates. No further action is required\n"
        except Exception as e:
            db.session.rollback()
            error_message += f"Error rolling back news update candidates: {e}\nManual rollback required\n"
        finally:
            error_message += "Affected candidates:\n"
            error_message += "\n".join(
                (f"candidate id: {original.id}, positions id: {original.positions_id}, last update: {original.last_update}, next update: {original.next_update}, update count: {original.update_count}" for original in candidates_of_a_given_law) for candidates_of_a_given_law in saved_for_rollback
            )
            error_message += f"\nExiting daily update at {datetime.datetime.now()}"
            logger.critical(error_message, subject="Google News is unresponsive")
    else:
        no_news_found = 0


def generate_search_queries(client : OpenAI, law : GesetzesVorhaben) -> list[str]:
    """Generates search queries for a given law. These can be used to search for news about the law."""

    # extract shorthand from law title, if there is one
    shorthand = extract_shorthand(law.titel)
    queries = []

    generate_search_queries_messages = [
        {
            "content": f"""Du erhältst vom Nutzer den amtlichen Titel eines deutschen Gesetzes. Dieser ist oft sperrig und klingt nach Behördensprache. 
Überlege zunächst, mit welchen Begriffen in Nachrichtenartikeln vermutlich auf dieses Gesetz Bezug genommen wird. 
Generiere dann 3 Suchanfragen zum Suchen nach Nachrichtenartieln über das Gesetz.
Hänge an jedes Wort innerhalb der einzelnen Suchanfragen ein * an. Verwende niemals Worte wie 'Nachricht' oder 'Meldung', die kenntlich machen sollen, dass nach Nachrichtenartikeln gesucht wird.  
Achte darauf, die einzelnen Suchanfragen nicht so restriktiv zu machen, dass relevante Nachrichtenartikel nicht gefunden werden. 
Wenn es dir beispielsweise gelingt, ein einzelnes Wort zu finden, das so passend und spezifisch ist, dass es höchstwahrscheinlich nur in Nachrichtenartikeln vorkommt, die auch tatsächlich von dem Gesetz handeln, dann solltest du dieses Wort nicht noch um weitere Worte ergänzen, sondern allein als eine der Suchanfragen verwenden. 
Deine Antwort MUSS ausschließlich aus JSON Daten bestehen und folgende Struktur haben:
{QUERIES_SCHEMA_DUMPS}""",
            "role": "system",
        },
        {"content": law.titel, "role": "user"},
    ]

    try:
        ai_response = get_structured_data_from_ai(
            client,
            generate_search_queries_messages,
            GENERATE_QUERIES_SCHEMA,
            "suchanfragen",
        )
        queries = [query for query in ai_response if query]

    except Exception as e:
        logger.critical(f"Error generating search query. Error: {e}. AI response: {ai_response}.", subject="Error generating search queries ")
        return None

    if shorthand and shorthand not in queries:
        queries.insert(0, shorthand)

    return queries


def extract_shorthand(titel : str) -> str:
    """Extract the shorthand (not the abbreviation) from a law's title. Probably better to do this with regex, but this works for now."""
    if titel.find("(") == -1 or not titel.endswith(")"):
        return ""
    
    shorthand_start = titel.rfind("(") + 1
    # (2. Betriebsrentenstärkungsgesetz) -> Betriebsrentenstärkungsgesetz
    while titel[shorthand_start].isdigit() or titel[shorthand_start] in {".", " "}:  
        shorthand_start += 1
    
    # (NIS-2-Umsetzungs- und Cybersicherheitsstärkungsgesetz) -> Cybersicherheitsstärkungsgesetz
    shorthand_start = max(shorthand_start, 
                          titel.find("- und ", start=shorthand_start, end=len(titel) - 1) + len("- und "))

    # (Sportfördergesetz - SpoFöG) -> Sportfördergesetz
    shorthand_end = titel.find(" - ", start=shorthand_start, end=len(titel) - 1) if titel.find(" - ", start=shorthand_start, end=len(titel) - 1) > 0 else len(titel) - 1  

    # same thing, except with long dash
    shorthand_end = titel.find(" – ", start=shorthand_start, end=len(titel) - 1) if titel.find(" – ", start=shorthand_start, end=len(titel) - 1) > 0 else len(titel) - 1  

    shorthand = f"{titel[shorthand_start:shorthand_end]}*"
    return shorthand


# def handle_embeddings():
#     law = get_law_by_id(302)
#     if (
#         beschluss_position := db.session.query(Vorgangsposition)
#         .filter(
#             Vorgangsposition.vorgangs_id == law.id,
#             Vorgangsposition.vorgangsposition == "Beschlussempfehlung und Bericht",
#         )
#         .one_or_none()
#     ):
#         beschluss_position_id = beschluss_position.id
#     if (
#         beschluss := db.session.query(Fundstelle)
#         .filter(Fundstelle.positions_id == beschluss_position_id)
#         .one_or_none()
#     ):
#         beschluss_url = beschluss.pdf_url
#     chunks = chunk_document(beschluss_url)

#     for i, chunk in enumerate(chunks):
#         chunk.page_content = chunk.page_content.replace(" ", "-").replace("  ", " ")
#         chunk.metadata.update(
#             {
#                 "law_id": law.id,
#                 "document_type": "Beschlussempfehlung",
#                 "document_id": str(beschluss_position_id),
#                 "chunk_number": i,
#             }
#         )
#     vector_store = SupabaseVectorStore.from_documents(
#         chunks,
#         embeddings,
#         client=supabase,
#         table_name="documents",
#         query_name="match_documents",
#     )
#     query = "Was sind die wichtigsten Unterschiede zwischen dem Gesetzentwurf und der Beschlussempfehlung des Ausschusses?"
#     matched_docs = vector_store.similarity_search(query)
#     logger.debug(matched_docs)
#     os._exit(0)


# def chunk_document(url):
#     tokenizer = OpenAITokenizerWrapper()
#     MAX_TOKENS = 8191

#     pipeline_options = PdfPipelineOptions()
#     pipeline_options.do_ocr = True
#     pipeline_options.do_table_structure = True
#     pipeline_options.table_structure_options.do_cell_matching = True

#     doc_converter = DocumentConverter(
#         format_options={
#             InputFormat.PDF: PdfFormatOption(
#                 pipeline_options=pipeline_options, backend=PyPdfiumDocumentBackend
#             )
#         }
#     )

#     loader = DoclingLoader(
#         file_path=url,
#         export_type=ExportType.DOC_CHUNKS,
#         converter=doc_converter,
#         chunker=HybridChunker(tokenizer=tokenizer, max_tokens=MAX_TOKENS),
#     )
#     splits = loader.load()

#     conv_result = doc_converter.convert(url)
#     with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".md", encoding='utf-8') as temp_file:
#         markdown_content = conv_result.document.export_to_markdown()
#         temp_file.write(markdown_content)
#         temp_file_path = temp_file.name  # Save the path

#     # File is now closed, we can use the loader
#     try:
#         loader = DoclingLoader(
#             file_path=temp_file_path,
#             export_type=ExportType.DOC_CHUNKS,
#             converter=doc_converter,
#             chunker=HybridChunker(tokenizer=tokenizer, max_tokens=MAX_TOKENS)
#         )
#         splits = loader.load()
#     finally:
#         # Clean up the temporary file
#         os.unlink(temp_file_path)

#     return splits


def map_pdf_without_destinations(fundstelle: Fundstelle, pdf: pypdfium2.PdfDocument) -> int:
    """Maps internal page numbers to external page numbers for a given document.Returns the external page number on which the internal page numbers start. Used for Dokumente from the BR, which do not have destinations set.
    """

    fundstelle_infos = f"Fundstelle with internal id: {fundstelle.id}, dip id: {fundstelle.dip_id}, url {fundstelle.pdf_url}"
    
    # Search the upper 15% of each page for any and all numbers and save them in a list of lists
    try:
        num_pages = len(pdf)
        pages = []
        search_area_percent = 0.15

        for page_idx in range(num_pages):
            page = pdf[page_idx]
            page_width, page_height = page.get_size()
            top_search_height = page_height * search_area_percent
            page_text = page.get_textpage()
            top_text = page_text.get_text_bounded(
                0, page_height - top_search_height, page_width, page_height
            )
            page_candidates = []
            nums = re.findall(r"\b\d+\b", top_text)
            for num in nums:
                try:
                    n = int(num)
                    page_candidates.append(n)
                except ValueError:
                    continue
            pages.append(page_candidates)

    except Exception as e:
        logger.critical(
            f"Failed to process page {page_idx} of {fundstelle_infos}. Error: {str(e)}",
            subject="Error searching for numbers on top of pdf pages",
        )

    # some setup that accounts for smaller / normal sized documents
    start = None
    offset = None
    done = False
    pages_missing_numbers = 0
    sequences = []
    pages_with_consecutive_numbers_threshold = (
        10 if len(pages) >= 20 else len(pages) // 2
    )
    verify_last_pages = (
        min(5, len(pages) - pages_with_consecutive_numbers_threshold)
        if len(pages) > 20
        else 0
    )

    # Keep going through the numbers from each page until we find a sequence of 10 (or less, for smaller documents) consecutive numbers. If we do, verify that the sequence holds by also checking the last 5 (or less, for smaller documents) pages.
    for i, page in enumerate(pages):
        if done:
            break

        # empty pages dont have numbers printed on them. This way, they don't break the sequence, but they don't count towards the threshold, either
        if not page:
            pages_missing_numbers += 1
            continue

        continued_sequences = []
        new_sequences = []

        for candidate in page:
            if done:
                break

            continues_sequence = False

            for j, sequence in enumerate(sequences):
                # dont append more than one number to each sequence per page
                if j in continued_sequences:
                    continue

                if candidate == sequence[-1] + 1 + pages_missing_numbers:
                    continues_sequence = True
                    sequence.append(candidate)
                    continued_sequences.append(j)

                    if len(sequence) >= pages_with_consecutive_numbers_threshold:
                        # if our sequence covers the length of the document, we are done
                        if not verify_last_pages or i >= len(pages) - verify_last_pages:
                            done = True
                            start = i - pages_with_consecutive_numbers_threshold + 1
                            offset = candidate - i
                            break
                        else:
                            # check if the sequence still holds for any of the last 5 pages
                            # (technically, just checking the last page should be enough, but this should be a bit more robust)
                            for k in range(
                                len(pages) - 1, len(pages) - 1 - verify_last_pages, -1
                            ):
                                if any(
                                    final_candidate == candidate + k - i
                                    for final_candidate in pages[k]
                                ):
                                    done = True
                                    start = (
                                        i - pages_with_consecutive_numbers_threshold + 1
                                    )
                                    offset = candidate - i
                                    break

                            if done:
                                break

                            # if it does not, report an error
                            logger.critical(
                                f"Found {pages_with_consecutive_numbers_threshold} consecutive numbers on pages {i - pages_with_consecutive_numbers_threshold} to {i}.\n"
                                f"However, none of the last {verify_last_pages} pages have the expected internal page number {candidate + len(pages) - i}.\n"
                                f"Error occurred on {fundstelle_infos}.",
                                subject="Failed to verify page number sequence against final pages",
                            )

            # if the candidate did not continue any sequences, it may be the start of a new sequence
            if not continues_sequence:
                new_sequences.append([candidate])

        pages_missing_numbers = 0

        # remove sequences that were not continued on the current page
        for j in range(len(sequences) - 1, -1, -1):
            if j not in continued_sequences:
                sequences.pop(j)

        sequences += new_sequences

    # return result or throw error. We need to return offset - 1, because our list was 0-indexed, but to the reader, pdf pages are 1-indexed (likewise, start would have to be +1, if it was going to be returned at all)
    if start and offset is not None:
        logger.info(
            f"Finished mapping internal page numbers for {fundstelle_infos}.\n"
            f"Internal page numbers start on internal page {start + 1} (1-indexed), which has external page number {start + offset}, making the offset {offset - 1}."
        )
        return offset -1 
    else:
        logger.critical(
            f"Could not find a sequence of {pages_with_consecutive_numbers_threshold} consecutive numbers on the first {len(pages)} pages.\n"
            f"Error occurred on {fundstelle_infos}.",
            subject="Could not find a sequence of page numbers",
        )


def update_all_pdf_urls():
    """Maps the pdf_url of all fundstellen from the Bundesrat for which this hasn't been done yet."""

    fundstellen = (
        db.session.query(Fundstelle)
        .filter(
            Fundstelle.pdf_url.like("%#P.%"),
            Fundstelle.herausgeber == "BR",
            Fundstelle.mapped_pdf_url == None,
        )
        .all()
    )
    fundstellen_groups = {}
    for fundstelle in fundstellen:
        fundstellen_groups[fundstelle.dokumentnummer] = fundstellen_groups.get(
            fundstelle.dokumentnummer, []
        ) + [fundstelle]
    for group in fundstellen_groups.values():
        offset = map_pdf_without_destinations(group[0])
        for fundstelle in group:
            try:
                internal_page = fundstelle.pdf_url.split("#P.")[1]
                external_page = int(internal_page) - offset
                fundstelle.mapped_pdf_url = fundstelle.pdf_url.replace(
                    f"#P.{internal_page}", f"#page={external_page}"
                )
                logger.debug(f"Old url: {fundstelle.pdf_url}")
                logger.debug(f"New url: {fundstelle.mapped_pdf_url}")
            except Exception as e:
                logger.debug(
                    f"Error mapping pdf url for fundstelle {fundstelle.id}: {e}, url: {fundstelle.pdf_url}"
                )
        db.session.commit()


def map_pdf_with_destinations(fundstelle: Fundstelle, pdf : pypdfium2.PdfDocument) -> dict:
    """
    Get all named destinations from a PDF file. Used for pdf files from the Bundestag, where internal page numbers are layed out as named destinations.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        A dictionary mapping destination names to page numbers
    """

    fundstelle_infos = f"Fundstelle with internal id: {fundstelle.id}, dip id: {fundstelle.dip_id}, url: {fundstelle.pdf_url}"
    if (
        not fundstelle.anfangsseite
        or not fundstelle.anfangsseite.isdigit()
        or not fundstelle.endseite
        or not fundstelle.endseite.isdigit()
    ):
        logger.critical(
            f"Error occurd on {fundstelle_infos}",
            subject="Missing anfangsseite or endseite",
        )
        return {}
    
    anfangsseite = int(fundstelle.anfangsseite)
    endseite = int(fundstelle.endseite)
    offset = endseite - anfangsseite
    if offset < 0:
        logger.critical(
            f"Error occurd on {fundstelle_infos}",
            subject="Anfangsseite is greater than endseite",
        )
        return {}

    url = fundstelle.pdf_url
    doc_handle = pdf.raw

    # get the count of named destinations
    count = pdfium_c.FPDF_CountNamedDests(doc_handle)

    destinations = {}

    # For each destination
    for i in range(count):

        # First, get the required buffer size
        buflen = ctypes.c_long(0)
        dest_handle = pdfium_c.FPDF_GetNamedDest(
            doc_handle, i, None, ctypes.byref(buflen)
        )

        if not dest_handle:
            logger.debug(f"No destination found for index {i}")
            continue

        # If buffer length is returned as <= 0, something went wrong
        if buflen.value <= 0:
            logger.warning(f"Error getting buffer size for destination {i}")
            continue

        # Allocate buffer for the destination name
        buffer = ctypes.create_string_buffer(buflen.value)

        # Second call to get the actual name
        pdfium_c.FPDF_GetNamedDest(doc_handle, i, buffer, ctypes.byref(buflen))

        # Skip the last 2 bytes which are null terminators
        name_bytes = buffer.raw[: buflen.value - 2]

        # Convert from UTF-16LE to Python string
        try:
            dest_name = name_bytes.decode("utf-16le")
            # Get the page index from the destination handle
            page_index = pdfium_c.FPDFDest_GetDestPageIndex(doc_handle, dest_handle)

            # Page indices are 0-based in PDFium, convert to 1-based for user-friendly display
            page_number = page_index + 1 if page_index >= 0 else None

            destinations[dest_name] = page_number
        except UnicodeDecodeError:
            logger.warning(
                f"Error decoding destination name or page number at index {i} / {count} for {fundstelle_infos}"
            )

    logger.info(f"found {len(destinations.keys())} named destinations")

    mapped_anfangsseite, mapped_endseite = None, None

    # The function should return at this point if the DIP values for anfangsseite and endseite are in the destinations dictionary
    if (mapped_anfangsseite := destinations.get(f"P.{anfangsseite}", None)) and (
        mapped_endseite := destinations.get(f"P.{endseite}", None)
    ):
        logger.info(f"Successfully mapped anfangsseite {anfangsseite} to external anfangsseite: {mapped_anfangsseite} and endseite {endseite} to external endseite {mapped_endseite} for {fundstelle_infos}")
        return destinations

    # if we get here, the DIP values for anfangsseite and endseite are not in the destinations dictionary, so we need to approximate them
    lowest_destination = min(
        int(k.split(".")[1])
        for k in destinations.keys()
        if k.startswith("P.") and k.split(".")[1].isdigit()
    )
    highest_destination = max(
        int(k.split(".")[1])
        for k in destinations.keys()
        if k.startswith("P.") and k.split(".")[1].isdigit()
    )

    def approximate_destination(seite):
        i = 1
        mapped_seite = None
        while (
            not (mapped_seite := destinations.get(f"P.{seite - i}", None))
            and seite - i >= lowest_destination
        ):
            i += 1
        if mapped_seite:
            return mapped_seite + i

        i = 1
        while (
            not (mapped_seite := destinations.get(f"P.{seite + i}", None))
            and seite + i <= highest_destination
        ):
            i += 1
        if mapped_seite:
            return mapped_seite - i

        logger.warning(
            f"Failed to approximate destination for {fundstelle_infos}, page: {seite}, destinations: {destinations}",
        )
        return None

    mapped_anfangsseite = mapped_anfangsseite or approximate_destination(anfangsseite)
    mapped_endseite = mapped_endseite or approximate_destination(endseite)

    # if the approximation failed for either anfangsseite or endseite, we try to approximate it based on the other one and the offset
    mapped_anfangsseite = mapped_anfangsseite or (
        mapped_endseite - offset if mapped_endseite else None
    )
    mapped_endseite = mapped_endseite or (
        mapped_anfangsseite + offset if mapped_anfangsseite else None
    )

    if mapped_anfangsseite and mapped_endseite:
        if mapped_anfangsseite > mapped_endseite:
            logger.critical(
                f"Invalid destination mapping - anfangsseite is greater than endseite. This happened on {fundstelle_infos}, anfangsseite: {anfangsseite}, endseite: {endseite}, mapped_anfangsseite: {mapped_anfangsseite}, mapped_endseite: {mapped_endseite}, destinations: {destinations}",
                subject="Failed to map destinations, anfangsseite is greater than endseite",
            )
            return {}
        else:
            destinations[f"P.{anfangsseite}"] = mapped_anfangsseite
            destinations[f"P.{endseite}"] = mapped_endseite
            logger.info(f"Successfully mapped anfangsseite {anfangsseite} to external anfangsseite: {mapped_anfangsseite} and endseite {endseite} to external endseite {mapped_endseite} for {fundstelle_infos}")
            return destinations
    else:
        logger.critical(
            f"Failed to map destinations for {fundstelle_infos}, destinations: {destinations}",
            subject="Failed to map destinations",
        )
        return {}

def launch():
    with app.app_context():
            if is_update_active():
                logger.critical(
                    f"Script already in progress. Immediately terminating new process at {datetime.datetime.now()}.",
                    subject="Daily update launched while still in progress.",
                )

            set_update_active(True)

            update_laws()
            update_news_update_candidates()

            set_update_active(False)

if __name__ == "__main__":
    launch() # hack to more easily run this from a different file
