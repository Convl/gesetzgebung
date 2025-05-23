from gesetzgebung.models import *
from gesetzgebung.logger import get_logger
import re
import time
import os
import smtplib
import datetime
import json
import time
from urllib.parse import quote

helpers_logger = get_logger(__name__)

bundeslaender = {
    "Bayern",
    "Niedersachsen",
    "Baden-Württemberg",
    "Nordrhein-Westfalen",
    "Brandenburg",
    "Mecklenburg-Vorpommern",
    "Hessen",
    "Sachsen-Anhalt",
    "Rheinland-Pfalz",
    "Sachsen",
    "Thüringen",
    "Schleswig-Holstein",
    "Saarland",
    "Berlin",
    "Hamburg",
    "Bremen",
}

genera = {
    "BR": "m",
    "BT": "m",
    "BRg": "w",
    "Bundestag": "m",
    "Bundesrat": "m",
    "Auswärtiger": "m",
    "Ausschuss": "m",
    "Fraktion": "w",
    "Bundesregierung": "w",
    "Bundesministerium": "n",
    "Bayern": "n",
    "Niedersachsen": "n",
    "Baden-Württemberg": "n",
    "Nordrhein-Westfalen": "n",
    "Brandenburg": "n",
    "Mecklenburg-Vorpommern": "n",
    "Hessen": "n",
    "Sachsen-Anhalt": "n",
    "Rheinland-Pfalz": "n",
    "Sachsen": "n",
    "Thüringen": "n",
    "Schleswig-Holstein": "n",
    "Saarland": "n",
    "Berlin": "n",
    "Hamburg": "n",
    "Bremen": "n",
}

praepositionen_nominativ = {  # "DER Bundestag legt ein Gesetz vor"
    "m": "der",
    "w": "die",
    "n": "das",
    "p": "die",
}

praepositionen_genitiv = {  # "...ein Gesetz DES Bundestags."
    "m": "des",
    "w": "der",
    "n": "des",
    "p": "der",
}

praepositionen_dativ = {  # "...legt DEM Bundesrat ein Gesetz vor"
    "m": "dem",
    "w": "der",
    "n": "dem",
    "p": "den",
}

praepositionen_akkusativ = {  # "... bringt ein Gesetz in DEN Bundesrat ein."
    "m": "den",
    "w": "die",
    "n": "das",
    "p": "die",
}


zuordnungen = {
    "BR": "Bundesrat",
    "BT": "Bundestag",
}

# Where multiple options exist for vorgangsposition, list the most normal one first, as that is the one that will be displayed if this event lies in the future (has_happened=False)
gesetzentwurf_bt = {
    "vorgangsposition": "Gesetzentwurf im Bundestag",
    "text": "Der Gesetzentwurf muss noch in den Bundestag eingebracht werden.",
}
gesetzentwurf_br = {
    "vorgangsposition": "Gesetzentwurf im Bundesrat",
    "text": "Der Gesetzentwurf muss noch in den Bundesrat eingebracht werden.",
}
gesetzesantrag_br = {
    "vorgangsposition": "Gesetzesantrag",
    "text": "Im Bundesrat muss noch ein Antrag auf Einbringung des Gesetzentwurfs in den Bundestag gestellt werden.",
}
erste_beratung = {
    "vorgangsposition": "1. Beratung",
    "text": "Die erste Beratung im Bundestag und Überweisung an die zuständigen Ausschüsse muss noch stattfinden.",
}
beschlussempfehlung = {
    "vorgangsposition": [
        "Beschlussempfehlung und Bericht",  # assumes that the Bericht is not absolutely necessary. Not sure if true.
        "Beschlussempfehlung",
    ],
    "text": "Der federführende Ausschuss muss noch den Bericht und die Beschlussempfehlung der zuständigen Ausschüsse vorlegen.",
}
zweite_beratung = {
    "vorgangsposition": "2. Beratung",
    "text": "Die zweite Beratung und Abstimmung über den Gesetzentwurf und die Beschlussempfehlung der Ausschüsse im Bundestag muss noch stattfinden.",
}
dritte_beratung = {
    "vorgangsposition": "3. Beratung",
    "text": "Die dritte Beratung und Abstimmung über den Gesetzentwurf und die Beschlussempfehlung der Ausschüsse im Bundestag muss noch stattfinden.",
}
zweite_und_dritte_beratung = {
    "vorgangsposition": "2. und 3. Beratung",
    "text": "If this ever gets displayed, it's a bug.",
}  # should never be displayed
zweite_beratung_und_schlussabstimmung = {
    "vorgangsposition": "2. Beratung und Schlussabstimmung",
    "text": "If this ever gets displayed, it's a bug.",
} # should never be displayed
entscheidender_durchgang_br = {
    "vorgangsposition": "Abstimmung im Bundesrat",
    "text": "Der Bundesrat muss noch über das Gesetz abstimmen.",
}
erster_durchgang_br = {
    "vorgangsposition": "1. Durchgang",
    "text": "Der erste Durchgang mit Stellungnahme des Bundesrats muss noch stattfinden.",
}
br_einbringungsbeschluss = {
    "vorgangsposition": "BR-Sitzung",
    "text": "Der Bundesrat muss noch beschließen, das Gesetz in den Bundestag einzubringen.",
}  # typischerweise gibt es 2x BR-Sitzung: 1x Ausschusszuweisung, 1x Einbringungsbeschluss (oder eben nicht). Ersteres ist aber nicht zwingend
abstimmung_ueber_vermittlungsvorschlag_im_bt = {
    "vorgangsposition": "Abstimmung über Vermittlungsvorschlag",
    "text": "Der Bundestag muss noch über den Vermittlungsvorschlag des Vermittlungsausschusses abstimmen.",
}
abstimmung_ueber_va_vorschlag_im_br = {
    "vorgangsposition": "BR-Sitzung",
    "text": "Der Bundesrat muss noch über den Vorschlagg des Vermittlungsausschusses abstimmen.",
}
ueberstimmung_des_br_bei_einspruchsgesetz = {"text": "Der Bundestag muss den vom Bundesrat erhobenen Einspruch noch überstimmen."}  # TODO: kann noch nicht ausgefüllt werden mangels Beispielsfall

position_descriptors = {
    "Gesetzentwurf im Bundestag": "Bei dieser Position handelt es sich um die Vorlage des ursprünglichen Gesetzentwurfs im Bundestag. Das hiermit verknüpfte Dokument ist der ursprüngliche Gesetzentwurf. Diese Position steht relativ am Anfang des Gesetzgebungsverfahrens. Falls der Urheber des Gesetzentwurfs die Bundesregierung ist, muss der Gesetzentwurf außerdem auch in den Bundesrat eingebracht werden.",
    "Gesetzentwurf im Bundesrat": "Bei dieser Position handelt es sich um die Vorlage des ursprünglichen Gesetzentwurfs im Bundesrat. Das hiermit verknüpfte Dokument ist der ursprüngliche Gesetzentwurf. Diese Position ist nur erforderlich, wenn der Gesetzentwurf von der Bundesregierung stammt.", 
    "1. Beratung": "Bei dieser Position handelt es sich um die erste Beratung des Gesetzentwurfs im Bundestag. Das hiermit verknüpfte Dokument ist das Plenarprotokoll der 1. Beratung des Gesetzentwurfs im Bundestag. Häufig enthält es Redebeiträge der Parlamentarier. Am Ende der 1. Beratung wird der Gesetzentwurf an die zuständigen Bundestagsausschüsse überwiesen.",
    "Zurückverweisung an die Ausschüsse in 2./3. Beratung": "Bei dieser Position handelt es sich um die 2. und 3. Beratung des Gesetzentwurfs im Bundestag, wobei der Gesetzentwurf weder angenommen noch abgelehnt, sondern zur erneuten Bearbeitung an die zuständigen Ausschüsse zurückverwiesen wird. Das mit dieser Position verknüpfte Dokument ist das Plernarprotokoll der betreffenden Beratung im Bundestag. Häufig enthält es Redebeiträge der Parlamentarier.",
    "Beschlussempfehlung und Bericht": "Bei dieser Position handelt es sich um den Bericht und die Beschlussempfehlung der zuständigen Bundestagsausschüsse. Das hiermit verknüpfte Dokument enthält die Beschlussempfehlung und den Bericht. Das Feld Urheber gibt den federführenden Ausschuss an. Der Bericht enthält die Einschätzung der zuständigen Ausschüsse zu dem Gesetzentwurf. Die Beschlussempfehlung kann beispielsweise lauten, den Gesetzentwurf abzulehnen, ihn mit Änderungen anzunehmen, oder ihn unverändert anzunehmen.",
    "Beschlussempfehlung": "Bei dieser Position handelt es sich um die Beschlussempfehlung der zuständigen Bundestagsausschüsse. Das hiermit verknüpfte Dokument enthält die Beschlussempfehlung. Das Feld Urheber gibt den federführenden Ausschuss an. Die Beschlussempfehlung kann beispielsweise lauten, den Gesetzentwurf abzulehnen, ihn mit Änderungen anzunehmen, oder ihn unverändert anzunehmen.",
    "Bericht": "Bei dieser Position handelt es sich um den Bericht der zuständigen Bundestagsausschüsse. Das hiermit verknüpfte Dokument enthält den Bericht. Das Feld Urheber gibt den federführenden Ausschuss an. Der Bericht enthält die Einschätzung der zuständigen Ausschüsse zu dem Gesetzentwurf.",
    "2. Beratung": "Bei dieser Position handelt es sich um die 2. Beratung des Gesetzentwurfs im Bundestag. Das hiermit verknüpfte Dokument enthält das Plenarprotokoll der Beratung. Häufig enthält es Redebeiträge der Parlamentarier zu dem Gesetzentwurf.",
    "2. Beratung und Schlussabstimmung": "Bei dieser Position handelt es sich um die 2. Beratung des Gesetzentwurfs, und die Schlussabstimmung über den Gesetzentwurf, im Bundestag. Der Gesetzentwurf wird hier vom Bundestag typischerweise entweder angenommen oder abgelehnt. Das mit dieser Position verknüpfte Dokument ist das betreffende Plenarprotokoll des Bundestags. Es enthält möglicherweise Redebeiträge der Parlamentarier zu dem Gesetzentwurf.", 
    "3. Beratung": "Bei dieser Position handelt es sich um die 3. und typischerweise letzte Beratung des Gesetzentwurfs im Bundestag. Der Gesetzentwurf wird hier vom Bundestag typischerweise entweder angenommen oder abgelehnt. Das mit dieser Position verknüpfte Dokument ist das betreffende Plenarprotokoll des Bundestags. Es enthält möglicherweise Redebeiträge der Parlamentarier zu dem Gesetzentwurf.",
    "2. und 3. Beratung": "Bei dieser Position handelt es sich um die 2. und 3. Beratung des Gesetzentwurfs im Bundestag. Der Gesetzentwurf wird hier vom Bundestag typischerweise entweder angenommen oder abgelehnt. Das mit dieser Position verknüpfte Dokument ist das betreffende Plenarprotokoll des Bundestags. Es enthält möglicherweise Redebeiträge der Parlamentarier zu dem Gesetzentwurf.",
    "1. Durchgang": "Bei dieser Position handelt es sich um die erste Beratung des Gesetzentwurfs im Bundesrat. Das mit dieser Position verknüpfte Dokument ist das betreffende Plenarprotokoll des Bundesrats. Es enthält möglicherweise Redebeiträge der Bundesratsmitglieder zu dem Gesetzentwurf.",
    "Abstimmung im Bundesrat": "Bei dieser Position handelt es sich um die Beratung und Abstimmung zum Gesetzentwurf im Bundesrat. Das mit dieser Position verknüpfte Dokument ist das betreffende Plenarprotokoll des Bundesrats. Es enthält möglicherweise Redebeiträge der Bundesratsmitglieder zu dem Gesetzentwurf.",
    "Gesetzesantrag": "Bei dieser Position handelt es sich um einen von einem oder mehreren Bundesländern im Bundesrat eingebrachten Antrag, der darauf zielt, dass der Bundesrat seinerseits einen Gesetzentwurf ins Gesetzgebungsverfahren einbringen soll. Das mit dieser Position verknüpfte Dokument ist der Entwurf des Gesetzes, das die Länder über den Bundesrat ins Gesetzgebungsverfahren einbringen möchten.",
    "Plenarantrag": "Bei dieser Position handelt es sich um einen von einem oder mehreren Bundesländern im Bundesrat eingebrachten Antrag, der im Zusammenhang mit einem Gesetzgebungsverfahren steht. Das mit dieser Position verknüpfte Dokument enthält den Inhalt des Antrags.",
    "BR-Sitzung": "Bei dieser Position handelt es sich um eine Bundesratssitzung zu dem Gesetzgebungsverfahren. Je nach Stadium des Gesetzgebungsverfahrens kann der Bundesrat hier beispielsweise beschließen, das Gesetz den zuständigen Bundesratsausschüssen zuzuweisen, die Einbringung in den Bundestag anzunehmen oder abzulehnen, dem Vorschlag des Vermittlungsausschusses zuzustimmen oder diesen abzulehnen. Das mit dieser Position verknüpfte Dokument ist das betreffende Plenarprotokoll des Bundesrats. Es enthält möglicherweise Redebeiträge der Bundesratsmitglieder zu dem Gesetzentwurf.",
    "Berichtigung zum Gesetzesbeschluss": "Bei dieser Position handelt es sich um eine Berichtigung zum Gesetzesbeschluss. Das hiermit verknüpfte Dokument enthält ein Plenarprotokoll, aus dem sich der Inhalt der Berichtigung ergibt.",
    "Unterrichtung über Anrufung des Vermittlungsausschusses durch die Bundesregierung": "Bei dieser Position handelt es sich um eine Anrufung des Vermittlungsausschusses durch die Bundesregierung, weil der Bundestag und der Bundesrat sich nicht über den Erlass des Gesetzes einigen können. Das hiermit verknüpfte Dokument ist kurz und eher formaler Natur, es ergibt sich daraus im Wesentlichen nur, dass die Bundesregierung den Vermittlungsausschuss anruft.",
    "Unterrichtung über Anrufung des Vermittlungsausschusses durch den Bundesrat": "Bei dieser Position handelt es sich um eine Anrufung des Vermittlungsausschusses durch den Bundesrat, weil der Bundestag und der Bundesrat sich nicht über den Erlass des Gesetzes einigen können. Das hiermit verknüpfte Dokument ist kurz und eher formaler Natur, es ergibt sich daraus im Wesentlichen nur, dass der Bundesrat den Vermittlungsausschuss anruft.",
    "Unterrichtung über Stellungnahme des Bundesrats und Gegenäußerung der Bundesregierung": "Bei dieser Position handelt es sich um eine Stellungnahme des Bundesrats und eine Gegenäußerung der Bundesregierung im Rahmen eines Vermittlungsverfahrens. Das hiermit verknüpfte Dokument enthält die Stellungnahme und die Gegenäußerung.",
    "Unterrichtung über Zustimmungsversagung durch den Bundesrat": "Bei dieser Position handelt es sich um die Unterrichtung über die Verweigerung der Zustimmung des Bundesrats zum Erlass des Gesetzes. Das hiermit verknüpfte Dokument ist knapp und eher formaler Natur und enthält im Wesentlichen die Information, dass der Bundesrat sich weigert, zuzustimmen.",
    "Vermittlungsvorschlag": "Bei dieser Position handelt es sich um einen Vermittlungsvorschlag des Vermittlungsausschusses, um Einigkeit zwischen dem Bundestag und dem Bundesrat in Hinblick auf den Erlass des Gesetzes herzustellen. Das hiermit verknüpfte Dokument enthält den Inhalt des Vermittlungsvorschlags.", 
    "Einigungsvorschlag": "Bei dieser Position handelt es sich um einen Einigungsvorschlag des Vermittlungsausschusses, um Einigkeit zwischen dem Bundestag und dem Bundesrat in Hinblick auf den Erlass des Gesetzes herzustellen. Das hiermit verknüpfte Dokument enthält den Inhalt des Einigungsvorschlags.", 
    "Abstimmung über Vermittlungsvorschlag": "Bei dieser Position handelt es sich um die Abstimmung über den Vermittlungsvorschlag des Vermittlungsausschusses. Das hiermit verknüpfte Dokument ist das Plenarprotokoll zu der Abstimmung. Es enthält möglicherweise Redebeiträge der Parlamentarier.",
    "Protokollerklärung/Begleiterklärung zum Vermittlungsverfahren": "Bei dieser Position handelt es sich um eine Protokollerklärung (= inhaltliche Stellungnahme) von einzelnen oder mehreren Mitgliedern des Bundestags oder des Bundesrats zum laufenden Vermittlungsverfahren. Das hiermit verknüpfte Dokument enthält die Protokollerklärung.",
    "Rücknahme der Vorlage": "Bei dieser Position handelt es sich um die Rücknahme einer Gesetzesvorlage. Das hiermit verknüpfte Dokument enthält das Plenarprotokoll, in welchem die Rücknahme erklärt wurde.",
    "Rücknahme des Antrags": "Bei dieser Position handelt es sich um die Rücknahme eines Gesetzesantrags. Das hiermit verknüpfte Dokument ist eher knapp und formaler Natur und enthält im Wesentlichen die Information, dass der Antrag zurückgenommen wurde.",
    "Unterrichtung": "Bei dieser Position handelt es sich um einen schriftlichen Bericht, der typischerweise von der Bundesregierung aus eigener Initiative auf Verlangen des Bundestags erstellt wird. Die Unterrichtung kann inhaltliche Stellungnahmen unterschiedlicher Art enthalten. Das hiermit verknüpfte Dokument enthält den Inhalt der Unterrichtung.",
}


# TODO: pfad bundestag anders bei bes. Eilbedürftigkeit?
basispfad = [
    gesetzentwurf_bt,
    erste_beratung,
    beschlussempfehlung,
    zweite_beratung,
    dritte_beratung,
    zweite_und_dritte_beratung,
    entscheidender_durchgang_br,
]
pfad_bundestag = basispfad  # + [gesetzentwurf_br]?
pfad_bundesregierung = [erster_durchgang_br] + pfad_bundestag
pfad_bundesrat = [gesetzesantrag_br, br_einbringungsbeschluss] + basispfad

pfade = {
    "Bundestag": pfad_bundestag,
    "Bundesregierung": pfad_bundesregierung,
    "Bundesrat": pfad_bundesrat,
}


def parse_actors(actors, kasus, capitalize=False, iterable=False):
    """Parses a list of actors into a string, applying prepositions according to the rules of German grammar as per the kasus provided,
    and adding 'und' in front of the last actor. Optionally, capitalizes first letter. Optionally, outputs a list instead of a string,
    with each actor as an item in the list."""

    result = "" if not iterable else []

    if type(actors) != list:
        actors = [actors]

    for actor in actors:
        first_word = actor.split(" ")[0]

        if first_word.endswith("ausschuss"):
            first_word = "Ausschuss"

        praeposition = kasus.get(genera.get(first_word, ""), "")

        if kasus == praepositionen_genitiv:
            if first_word in bundeslaender:  # "des LANDES Bayern"
                praeposition += " Landes"
            elif genera[first_word] == "m":
                if actor.startswith("Ausschuss"):
                    actor = actor[:9] + "es" + actor[9:]  # "des AusschussES für Familie, Bildung..."
                else:
                    actor += "es"  # "des BundestagES"
            elif genera[first_word] == "n":  # "des BundesministeriumS"
                actor += "s"
        else:
            if first_word in bundeslaender:  # "das LAND Bayern"
                praeposition += " Land"

        result += f"{praeposition} {actor}, " if not iterable else [f"{praeposition} {actor}"]

    if not iterable:
        result = result[:-2]

    if capitalize:
        if not iterable:
            result = "D" + result[1:]
        else:
            result[0] = "D" + result[0][1:]

    if len(actors) > 1 and not iterable:
        last_comma = result.rfind(",", 0, len(result) - 1 - len(actor))
        result = result[:last_comma] + " und" + result[last_comma + 1 :]

    return result


def parse_beschluesse(law, beschluesse: List[Beschlussfassung]) -> str:  #
    """Parses a Beschlussfassung in the Bundestag."""

    text = "<ul>"

    for beschluss in beschluesse:
        text += "<li>"
        text += f"<strong>{beschluss.beschlusstenor}</strong>"

        if beschluss.dokumentnummer:
            text += " in Bezug auf: "
            dokumentnummern = [dokumentnummer.strip() for dokumentnummer in beschluss.dokumentnummer.split(",")]

            if len(dokumentnummern) > 1:
                text += "<ul>"

            for dokumentnummer in dokumentnummern:
                fundstellen_infos = (
                    db.session.query(Fundstelle.drucksachetyp, Fundstelle.pdf_url, Fundstelle.urheber)
                    .join(Vorgangsposition)
                    .filter(
                        Vorgangsposition.vorgangs_id == law.id,
                        Fundstelle.dokumentnummer == dokumentnummer,
                    )
                    .all()
                )

                for drucksachetyp, pdf_url, urheber in fundstellen_infos:

                    if not drucksachetyp:
                        drucksachetyp = "Dokument"

                    anmerkung = (
                        beschluss.abstimm_ergebnis_bemerkung if beschluss.abstimm_ergebnis_bemerkung and beschluss.abstimm_ergebnis_bemerkung.startswith(", Anmerkung") else (f", Stimmen(pro/contra/Enthaltung): {beschluss.abstimm_ergebnis_bemerkung}" if beschluss.abstimm_ergebnis_bemerkung else "")
                    )

                    text += (
                        f' <a href="{pdf_url}">{drucksachetyp}</a> (Urheber: {", ".join(urh for urh in urheber)}, Dokumentnummer: {dokumentnummer}{anmerkung})'
                        if len(dokumentnummern) == 1
                        else f'<li><a href="{pdf_url}">{drucksachetyp}</a> (Urheber: {", ".join(urh for urh in urheber)}, Dokumentnummer: {dokumentnummer}{anmerkung})</li>'
                    )

            if len(dokumentnummern) > 1:
                text += "</ul>"

        else:
            text += f" (Anmerkung: {beschluss.abstimm_ergebnis_bemerkung})" if beschluss.abstimm_ergebnis_bemerkung else ""

        text += "</li>"

    text += "</ul>"
    text += "\n"
    return text


def merge_beschluesse(beschluesse: List[BeschlussfassungDisplay], zweite_und_dritte_beratung=False) -> List[BeschlussfassungDisplay]:
    """Merge Beschlüsse which differ only in their .abstimm_ergebnis_bemerkung by concatenating their abstimm_ergebnis_bemerkung.
    Can merge Beschlüsse from a single Beratung or from a second and third Beratung. In the latter case, assumes that all beschluesse from
    the second beratung come first, followed by all from the third beratung, and takes a dict zweite_und_dritte_beratung to indicates which
    beschluesse belong to which beratung."""

    merged_beschluesse = (
        {
            "2. Beratung": [],
            "3. Beratung": [],
            "2. und 3. Beratung": [],
        }
        if zweite_und_dritte_beratung
        else []
    )

    merged_indices = set()

    if zweite_und_dritte_beratung:
        zweite, dritte = zweite_und_dritte_beratung.keys()

    for i in range(len(beschluesse)):
        if i in merged_indices:
            continue

        contains_beschluesse_from = {beschluesse[i].positions_id}
        merged = beschluesse[i]
        first_beschluss_from_dritte_beratung = True

        for j in range(i + 1, len(beschluesse)):
            if j in merged_indices:
                continue

            if beschluesse[i].dokumentnummer == beschluesse[j].dokumentnummer and beschluesse[i].beschlusstenor == beschluesse[j].beschlusstenor:

                if beschluesse[i].abstimm_ergebnis_bemerkung != beschluesse[j].abstimm_ergebnis_bemerkung:
                    contains_beschluesse_from.add(beschluesse[j].positions_id)

                    if not merged.abstimm_ergebnis_bemerkung:
                        merged.abstimm_ergebnis_bemerkung = ""

                    if not zweite_und_dritte_beratung:
                        merged.abstimm_ergebnis_bemerkung += f" // {beschluesse[j].abstimm_ergebnis_bemerkung}"
                    else:
                        if beschluesse[j].positions_id != beschluesse[i].positions_id:

                            if first_beschluss_from_dritte_beratung:
                                merged.abstimm_ergebnis_bemerkung = ", Anmerkung aus der zweiten Beratung: " + merged.abstimm_ergebnis_bemerkung if merged.abstimm_ergebnis_bemerkung else ""

                            merged.abstimm_ergebnis_bemerkung += ", Anmerkung aus der dritten Beratung: " + beschluesse[j].abstimm_ergebnis_bemerkung if beschluesse[j].abstimm_ergebnis_bemerkung else ""

                            first_beschluss_from_dritte_beratung = False
                        else:
                            merged.abstimm_ergebnis_bemerkung += f" // {beschluesse[j].abstimm_ergebnis_bemerkung}" if beschluesse[j].abstimm_ergebnis_bemerkung else ""

                merged_indices.add(j)
                contains_beschluesse_from.add(beschluesse[j].positions_id)

        if zweite_und_dritte_beratung:
            if zweite in contains_beschluesse_from and dritte in contains_beschluesse_from:
                merged_beschluesse["2. und 3. Beratung"].append(merged)
            elif zweite in contains_beschluesse_from:
                merged_beschluesse["2. Beratung"].append(merged)
            else:
                merged_beschluesse["3. Beratung"].append(merged)
        else:
            merged_beschluesse.append(merged)

        merged_indices.add(i)

    return merged_beschluesse


def create_link(position):
    text = position.abstract
    dokumentnummern = re.findall(r"Drs (\d{2}/\d{1,4})", position.abstract)
    for dokumentnummer in dokumentnummern:
        first_position_subquery = (
            db.session.query(
                Vorgangsposition.vorgangs_id,
                func.min(Vorgangsposition.id).label("first_pos_id"),
            )
            .group_by(Vorgangsposition.vorgangs_id)
            .subquery()
        )
        results = (
            db.session.query(GesetzesVorhaben)
            .join(
                first_position_subquery,
                GesetzesVorhaben.id == first_position_subquery.c.vorgangs_id,
            )
            .join(
                Vorgangsposition,
                Vorgangsposition.id == first_position_subquery.c.first_pos_id,
            )
            .join(Fundstelle)
            .filter(Fundstelle.dokumentnummer == dokumentnummer)
            .all()
        )
        if results:
            encoded_titel = quote(re.sub(r"\s+", "-", results[0].titel).lower())
            text = text.replace(
                dokumentnummer,
                f'<a href="/submit/{encoded_titel}?id={results[0].id}">{dokumentnummer}</a>',
            )
    return text


def report_error(subject, message, terminate=False):
    print(f"{subject}\n{message}")

    ERROR_MAIL_PASSWORD = os.environ.get("ERROR_MAIL_PASSWORD")
    ERROR_MAIL_ADDRESS = os.environ.get("ERROR_MAIL_ADDRESS")
    ERROR_MAIL_SMTP = "smtp.gmail.com"
    DEVELOPER_MAIL_ADDRESS = os.environ.get("DEVELOPER_MAIL_ADDRESS")
    try:
        with smtplib.SMTP(ERROR_MAIL_SMTP) as connection:
            connection.starttls()
            connection.login(ERROR_MAIL_ADDRESS, ERROR_MAIL_PASSWORD)
            connection.sendmail(
                ERROR_MAIL_ADDRESS,
                DEVELOPER_MAIL_ADDRESS,
                f"Subject: {subject}\n\n{message}",
            )
            connection.close()
    except Exception as e:
        print(f"CRITICAL: Failed to report critical error via email. Error: {e}. Message: {subject}\n{message}")

    if terminate:
        set_update_active(False)
        os._exit(1)


def get_structured_data_from_ai(client, messages, schema=None, subfield=None, models=None, temperature=0.3):
    # models = ['deepseek/deepseek-r1', 'deepseek/deepseek-chat', 'openai/gpt-4o-2024-11-20']
    models = models or ["deepseek/deepseek-r1"]
    delay = 1


    for retry in range(13):
        # Openrouter models parameter is supposed to pass the query on to the next model if the first one fails, but currently only works for some types of errors, so we manually iterate
        for i, model in enumerate(models):
            try:
                response = client.chat.completions.create(
                    model=model,
                    extra_body={
                        "models": models[i + 1 :],
                        "provider": {"require_parameters": True, "sort": "throughput"},
                        "temperature": temperature,
                    },
                    messages=messages,
                    response_format={"type": "json_schema", "json_schema": schema},
                )
                if response.choices:
                    break
            except Exception as e:
                print(f"Error with model {model}: {e}, messages: {messages}")
            
        try:
            ai_response = response.choices[0].message.content
            ai_response = re.sub(r"<think>.*?</think>", "", ai_response, flags=re.DOTALL)
            ai_response = re.sub(r"```json\n(.*?)\n```", r"\1", ai_response, flags=re.DOTALL)
            ai_response = json.loads(ai_response).get(subfield, None) if subfield else json.loads(ai_response)
            return ai_response

        except Exception as e:
            # TODO: this may crash if ai_response never gets assigned and/or response does not have these attrs.
            try:
                print(f"Could not parse AI response {ai_response}\nFrom: {response.choices[0].message.content}\n\n Error: {e}. Retrying in {delay} seconds.")
            except Exception as e2:
                print(f"Could not parse ai response or even report it back. Error: {e2}. Prior error: {e}")
            time.sleep(delay)
            delay *= 2

    helpers_logger.critical(
        "Error getting structured data from AI",
        f"Could not get structured data from AI. Time: {datetime.datetime.now()}, Messages: {messages}. Schema: {schema}. Subfield: {subfield}.",
    )


def get_text_data_from_ai(client, messages, models=None, stream=False, temperature=0.5):
    # models = ['deepseek/deepseek-r1', 'deepseek/deepseek-chat', 'openai/gpt-4o-2024-11-20']
    models = models or ["deepseek/deepseek-r1"]
    if not stream:
        delay = 1
        for retry in range(13):
            # Openrouter models parameter is supposed to pass the query on to the next model if the first one fails, but currently only works for some types of errors, so we manually iterate
            for i, model in enumerate(models):
                response = client.chat.completions.create(
                    model=model,
                    extra_body={
                        "models": models[i + 1 :],
                        "provider": {"sort": "throughput"},
                        "temperature": temperature,
                    },
                    messages=messages,
                )
                if response.choices:
                    break

            try:
                ai_response = response.choices[0].message.content
                # this shouldn't be necessary, but just in case
                ai_response = re.sub(r"<think>.*?</think>", "", ai_response, flags=re.DOTALL)
                ai_response = re.sub(r"```json\n(.*?)\n```", r"\1", ai_response, flags=re.DOTALL)
                return ai_response

            except Exception as e:
                print(f"Could not parse AI response {ai_response}\nFrom: {response.choices[0].message.content}\n\n Error: {e}. Retrying in {delay} seconds.")
                time.sleep(delay)
                delay *= 2

        helpers_logger.critical(
            "Error getting structured data from AI",
            f"Could not get text data from AI. Time: {datetime.datetime.now()}, Messages: {messages}.",
        )
    else:
        for i, model in enumerate(models):
            try:
                stream_response = client.chat.completions.create(
                    model=model,
                    extra_body={
                        "models": models[i + 1 :],
                        "provider": {"sort": "throughput"},
                        "temperature": 0.5,
                    },
                    messages=messages,
                    stream=True,  # Enable streaming
                )

                # Return a generator that yields each chunk
                def generate():
                    full_text = ""
                    last_activity = time.time()
                    idle_timeout = 20

                    try:
                        for chunk in stream_response:
                            if hasattr(chunk, "error") or (hasattr(chunk, "object") and chunk.object == "error"):
                                error_details = getattr(chunk, "error", {})
                                error_message = getattr(error_details, "message", "Unknown provider error")
                                error_code = getattr(error_details, "code", "unknown")

                                formatted_error = f"Error: {error_message}"
                                if error_code != "unknown":
                                    formatted_error += f" (code: {error_code})"

                                print(f"Received error event in stream: {formatted_error}")
                                yield {
                                    "chunk": formatted_error,
                                    "error": "provider_error",
                                }

                            last_activity = time.time()

                            if hasattr(chunk.choices[0], "delta") and hasattr(chunk.choices[0].delta, "content"):
                                content = chunk.choices[0].delta.content
                                if content is not None:
                                    full_text += content
                                    yield {"chunk": content, "full_text": full_text}

                            # Check for finish reason if available
                            if hasattr(chunk.choices[0], "finish_reason") and chunk.choices[0].finish_reason:
                                print(f"Stream finished with reason: {chunk.choices[0].finish_reason}")
                                break
                            current_time = time.time()
                            if current_time - last_activity > idle_timeout:
                                print(f"Stream idle for {idle_timeout} seconds, terminating")
                                if full_text:
                                    yield {
                                        "chunk": "\n\n[Response timed out]",
                                        "full_text": full_text + "\n\n[Response timed out]",
                                        "error": "stream_timeout",
                                    }
                                break

                    except Exception as e:
                        print(f"Exception in chunk processing: {e}")
                        print(f"Exception type: {type(e)}")
                        print(f"Exception dir: {dir(e)}")

                        yield {"chunk": f"Error: {str(e)}", "error": True}

                return generate()

            except Exception as e:
                print(f"Error with model {model}: {e}")
                print(f"Exception type: {type(e)}")
                print(f"Exception dir: {dir(e)}")

                def error_generator():
                    yield {"chunk": f"Error: {str(e)}", "error": True}

                return error_generator()

    helpers_logger.critical(
        "Error getting streaming data from AI",
        f"All models failed for streaming request. Time: {datetime.datetime.now()}, Messages: {messages}.",
    )

    # Return an empty generator
    def empty_generator():
        yield {
            "chunk": "Error: All models failed",
            "full_text": "Error: All models failed",
        }

    return empty_generator()

def assess_response_quality(client, models=None, questions=None, expected=None, messages=None, dokumente_list=None, schema=None, schema_propperty=None, schema_key=None, iterations=None):
    # below default test values assume this gets called with messages and dokumente_list set up for "Gesetz zur Änderung des BND-Gesetzes"

    models = models or {"deepseek/deepseek-r1": [],
                        "qwen/qwen3-235b-a22b": [],
                        "deepseek/deepseek-chat-v3-0324": [],
                        "meta-llama/llama-4-maverick": [],
                        "deepseek/deepseek-chat": [],
                        "qwen/qwen-2.5-72b-instruct": [],
                        }
    
    questions = questions or ["Fasse die wesentlichen Inhalte des ursprünglichen Gesetzentwurfs zusammen", 
                                "Fasse die Redebeiträge im Bundestag zusammen", 
                                "Fasse die Redebeiträge im Bundesrat zusammen", 
                                "Fasse die Ausschussempfehlung zusammen", 
                                "Was sind die wesentlichen Unterschiede zwischen dem Regierungsentwurf und der Ausschussfassung?"] # only this question fails, but fails in more reliabe ways for deepseek-r1
    
    expected = expected or [[1, 1, 0, 0, 0, 0, 0],
                            [0, 0, 1, 0, 0, 1, 0],
                            [0, 0, 0, 1, 0, 0, 1],
                            [0, 0, 0, 0, 1, 0, 0],
                            [1, 1, 0, 0, 1, 0, 0]]

    for model in models:
            for i in range(len(questions) * 10):
                messages[1]["content"] = f"""Meine Frage lautet: {questions[i//10]}\n\n
    Hier ist die Liste der Dokumente, die zu diesem Gesetz gehören:\n\n 
    {json.dumps(dokumente_list, ensure_ascii=False, indent=4)}"""
                time.sleep(2)
                response = get_structured_data_from_ai(client, messages, schema, schema_propperty, [model], 0.1)
                received = [result[schema_key] for result in response]
                for j, result in enumerate(response):
                    if result[schema_key] != expected[i//10][j]:
                        models[model].append({
                            "Question": questions[i//10],
                            "Expected": expected[i//10],
                            "Received": received[:]
                        })
                        break
            print(f"Model {model} has {len(models[model])} deviations in total.")
    
    return models