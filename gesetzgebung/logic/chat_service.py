import json

from gesetzgebung.logic.ai_helpers import get_text_data_from_ai, query_ai
from gesetzgebung.infrastructure.models import Dokument, db
from gesetzgebung.logic.ai_client import client

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


def chat_completion(user_message, infos, law_titel):
    dokument_ids = [id for info in infos for id in info.get("dokument_ids", [])]
    dokument_data = db.session.query(Dokument).filter(Dokument.id.in_(dokument_ids)).all()
    dokument_data = {dok.id: dok for dok in dokument_data}
    dokumente = []
    for info in infos:
        for dokument_id in info.get("dokument_ids", []):
            dokument = dokument_data[dokument_id]
            dokumente.append(
                {
                    "id": len(dokumente) + 1,
                    "Datum": info["datum"],
                    "Titel": info["vorgangsposition"],
                    "Urheber": (
                        ", ".join(urh for urh in info.get("urheber", []))
                        if info.get("urheber", None)
                        else (
                            "Bundestag"
                            if dokument.herausgeber == "BT"
                            else "Bundesrat"
                            if dokument.herausgeber == "BR"
                            else "Unbekannt"
                        )
                    ),
                    "Beschreibung": info["text"],
                    "Allgemeines": position_descriptors[info["vorgangsposition"]],
                    "Inhalt": dokument.markdown,
                    "Länge": (dokument.endseite - dokument.anfangsseite) + 1,
                }
            )

    yield f"data: {json.dumps({'stage': 'status', 'chunk': f'Zu diesem Gesetz liegen {len(dokumente)} Dokumente vor. <br>Filtere nach für die Frage relevanten Dokumenten. Dies kann einen Augenblick dauern...'})}\n\n"

    dokumente_for_filtering = [
        {k: v for k, v in dokument.items() if k not in {"Inhalt", "Länge"}} for dokument in dokumente
    ]
    filter_documents_schema = {
        "name": "Filter_Dokumente_Schema",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "positionen": {
                    "type": "array",
                    "description": "Die Liste der von dir bewerteten Vorgangspositionen",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "index": {
                                "type": "number",
                                "description": "Die Indexnummer einer Vorgangsposition",
                            },
                            "passend": {
                                "type": "number",
                                "description": "1, wenn das Dokument mit näheren Informationen zu der Vorgangsposition mit dieser Indexnummer zur Beantwortung der Frage des Nutzers voraussichtlich hilfreich sein wird, andernfalls 0",
                            },
                        },
                        "required": ["index", "passend"],
                    },
                }
            },
            "required": ["positionen"],
        },
    }

    filter_documents_messages = [
        {
            "role": "system",
            "content": f"""Du bist ein Experte im Beantworten von Fragen zu deutschen Gesetzen.
Der Nutzer hat eine Frage zu dem Gesetz mit dem amtlichen Titel {law_titel}.
Der Nutzer wird dir seine Frage sowie eine Liste von Vorgangspositionen im Gesetzgebungsverfahren dieses Gesetzes schicken.
Du sollst die Frage noch NICHT beantworten.
Stattdessen sollst du dir die Liste der Stationen anschauen und dir zu jeder davon überlegen, ob ein Dokument mit detaillierten Informationen zu dieser Vorgangsposition voraussichtlich hilfreich sein wird, um die Frage zu beantworten.                
Zu jeder Vorgangsposition sind folgende Felder angeggeben:
id: Eine Indexnummer zur Identifikation der Vorgangsposition.
Datum: Das Datum, an dem diese Vorgangsposition stattgefunden hat.
Titel: Der Titel, der beschreibt, um was für eine Vorgangsposition es sich handelt.
Urheber: Die Stelle, von der die Initiative zu dieser Vorgangsposition ausgeht, und von der das Dokument mit den detaillierten Informationen zu dieser Vorgangsposition stammt.
Beschreibung: Eine kurze Beschreibung dessen, was in dieser Vorgangsposition passiert ist.
Allgemeines: Allgemeine Informationen zu dieser Art von Vorgangsposition und den Inhalten des damit verknüpften Dokuments.
In deiner Antwort wirst du für jede Vorgangsposition in das Feld 'passend' entweder eine 1 (wenn du das zugehörige Dokument mit detaillierten Informationen für sinnvoll zur Beantwortung der Frage hältst) oder eine 0 (wenn du das zueghörige Dokument mit detaillierten Informationen für nicht sinnvoll zur Beantwortung der Frage hältst) eintragen.
Deine Antwort wird ausschließlich aus JSON Daten bestehen und folgende Struktur haben: {json.dumps(filter_documents_schema, ensure_ascii=False, indent=4)}""",
        },
        {
            "role": "user",
            "content": f"""Meine Frage lautet: {user_message}\n\n
Hier ist die Liste der Dokumente, die zu diesem Gesetz gehören:\n\n 
{json.dumps(dokumente_for_filtering, ensure_ascii=False, indent=4)}""",
        },
    ]

    # quality = assess_response_quality(client=client, messages=filter_documents_messages, dokumente_list=dokumente_list, schema=filter_documents_schema, schema_propperty="positionen", schema_key="passend")
    # meta-llama/llama-4-maverick and qwen/qwen3-235b-a22b were pretty much tied in assess_response_quality. Need to run tie-breaker with other questions / law

    try:
        # ai_response = get_structured_data_from_ai(client, filter_documents_messages, filter_documents_schema, "positionen", models=["meta-llama/llama-4-maverick", "qwen/qwen3-235b-a22b"])
        ai_response = query_ai(
            client=client,
            messages=filter_documents_messages,
            schema=filter_documents_schema,
            subfield="positionen",
            models=["meta-llama/llama-4-maverick", "qwen/qwen3-235b-a22b"],
            structured=True,
            stream=False,
            attempts=3,
        )
        if len(dokumente) != len(ai_response):
            raise Exception(
                f"{len(dokumente)} Documents were submitted, but {len(ai_response)} Documents were evaluated."
            )
    except Exception as e:
        yield f"data: {json.dumps({'stage': 'error', 'chunk': f'Beim Filtern der Dokumente ist ein Fehler aufgetreten: {str(e)}'})}\n\n"
        return

    for i in range(len(ai_response) - 1, -1, -1):
        if ai_response[i]["passend"] == 0:
            dokumente.pop(i)

    for i, doc in enumerate(dokumente):
        doc["id"] = i + 1

    if not dokumente:
        yield f"data: {json.dumps({'stage': 'status', 'chunk': 'Es wurden keine zur Beantwortung der Frage relevanten Dokumente gefunden. Die Antwort erfolgt auf Basis allgemein verfügbarer Informationen.'})}\n\n"
    else:
        doc_list_message = "Folgende Dokumente werden für die Beantwortung verwendet:"
        word_count, page_count = 0, 0
        for i, doc in enumerate(dokumente):
            doc_list_message += f"\n\n**{i + 1}. Dokument**<br>"
            doc_list_message += f"Urheber: {doc['Urheber']}<br>"
            doc_list_message += f"Vorgangsposition: {doc['Titel']}<br>"
            word_count += len(doc["Inhalt"].split())
            page_count += doc["Länge"]

        yield f"data: {json.dumps({'stage': 'status', 'chunk': doc_list_message})}\n\n"
        yield f"data: {json.dumps({'stage': 'status', 'chunk': f'Generiere eine Antwort auf Basis dieser Dokumente. Die Dokumente umfassen insgesamt {word_count} Wörter auf {page_count} Seiten. Dies kann einen Augenblick dauern...'})}\n\n"

    answer_question_messages = [
        {
            "role": "system",
            "content": f"""Du bist ein Experte im Beantworten von Fragen zu deutschen Gesetzen. 
Der Nutzer hat eine Frage zu dem Gesetz mit dem amtlichen Titel {law_titel}.
Der Nutzer wird dir seine Frage sowie eine Liste von Dokumenten schicken, die zu diesem Gesetz gehören.
Manche dieser Dokumente sind möglicherweise Auszüge aus längeren Dokumenten; dies kann insbesondere bei Plenarprotokollen der Fall sein. 
In dem Fall ist es möglich, dass am Anfang und / oder am Ende des Dokuments zunächst noch Text steht, der sich auf ein anderes Gesetz bezieht. 
Falls das der Fall ist, sollst du diesen Text ignorieren, und dich ausschließlich mit dem Teil des Dokuments befassen, der sich auf das Gesetz mit dem amtlichen Titel {law_titel} bezieht.
Nutze die angefügten Dokumente, wenn und soweit sie zur Beantwortung der Frage des Nutzers hilfreich sind.""",
        },
        {
            "role": "user",
            "content": f"""Meine Frage lautet: {user_message}\n\n
            Hier ist die Liste der Dokumente, die zu diesem Gesetz gehören:\n\n 
            {json.dumps(dokumente, ensure_ascii=False, indent=4)}""",
        },
    ]

    try:
        print("About to start streaming response")
        streaming_response = get_text_data_from_ai(
            client,
            answer_question_messages,
            models=["google/gemini-2.5-pro"],
            stream=True,
            temperature=0.2,
        )
        # streaming_response = query_ai(
        #     client=client,
        #     messages=answer_question_messages,
        #     models=["google/gemini-2.5-pro"],
        #     stream=True,
        #     temperature=0.2,
        #     attempts=3
        # )

        print("Got streaming response generator, starting to yield chunks")
        chunk_count = 0

        for chunk in streaming_response:
            try:
                # Debug info
                chunk_count += 1
                if chunk_count % 10 == 0:
                    print(f"Processed {chunk_count} chunks")

                # Make sure chunk is serializable
                if chunk.get("error", False):
                    # Just pass through the error message
                    yield f"data: {json.dumps({'stage': 'error', 'chunk': chunk['chunk']})}\n\n"
                    break
                else:
                    yield f"data: {json.dumps({'stage': 'answer', **chunk})}\n\n"

            except Exception as chunk_error:
                print(f"Error processing chunk: {chunk_error}")
                error_msg = f"Fehler beim Verarbeiten eines Teils der Antwort: {str(chunk_error)}"
                yield f"data: {json.dumps({'stage': 'error', 'chunk': error_msg})}\n\n"
                break

        print(f"Finished streaming response, processed {chunk_count} chunks")

    except Exception as stream_error:
        print(f"Error during streaming: {stream_error}")
        error_message = f"Bei der Generierung der Antwort ist ein Fehler aufgetreten: {str(stream_error)}"
        yield f"data: {json.dumps({'stage': 'error', 'chunk': error_message})}\n\n"
