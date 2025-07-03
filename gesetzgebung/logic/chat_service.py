import json

from gesetzgebung.helpers import get_text_data_from_ai, position_descriptors, query_ai
from gesetzgebung.logic.ai_client import client
from gesetzgebung.models import Dokument, Fundstelle, db


def chat_completion(user_message, infos, law_titel):
    dokument_ids = [id for info in infos for id in info.get("dokument_ids", [])]
    dokumente_mit_fundstellen = (
        db.session.query(Dokument, Fundstelle)
        .join(Fundstelle, Dokument.fundstelle_id == Fundstelle.id)
        .filter(Dokument.id.in_(dokument_ids))
        .all()
    )
    dokumente_mit_fundstellen = {
        dok.id: (dok, fundstelle) for dok, fundstelle in dokumente_mit_fundstellen
    }
    dokumente = []
    for info in infos:
        for dokument_id in info.get("dokument_ids", []):
            dokument, fundstelle = dokumente_mit_fundstellen[dokument_id]
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
                    "Der Inhalt des Dokuments lautet": dokument.markdown,
                    "Länge": (fundstelle.endseite - fundstelle.anfangsseite) + 1,
                }
            )

    yield f"data: {json.dumps({'stage': 'status', 'chunk': f'Zu diesem Gesetz liegen {len(dokumente)} Dokumente vor. <br>Filtere nach für die Frage relevanten Dokumenten. Dies kann einen Augenblick dauern...'})}\n\n"

    dokumente_for_filtering = [
        {
            k: v
            for k, v in dokument.items()
            if k not in {"Der Inhalt des Dokuments lautet", "Länge"}
        }
        for dokument in dokumente
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
            word_count += len(doc["Der Inhalt des Dokuments lautet:"].split())
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
