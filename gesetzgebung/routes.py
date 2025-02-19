import newspaper.configuration
from gesetzgebung.es_file import es, ES_LAWS_INDEX
from gesetzgebung.flask_file import app
# from gesetzgebung.models import * # TODO: just in case of issues: this used to be here and not in config.py, but db.create_all() needs models 
from gesetzgebung.helpers import *
# from gesetzgebung.daily_update import daily_update # TODO: no idea what that was doing here
from flask import render_template, request, jsonify
import datetime
import copy
import re
import os
import json
from openai import OpenAI
import newspaper
from gnews import GNews
from googlenewsdecoder import gnewsdecoder
import re

def extract_abbreviation(titel):
    # Extract the shorthand (not the abbreviation) from the title of a law, if there is one
    parentheses_start = max(6, titel.rfind("(")) # There will never be a ( before index 6, max is just in case there is a ) without a ( in the title
    abbreviation_start = parentheses_start + 1
    while titel[abbreviation_start].isdigit() or titel[abbreviation_start] in {".", " "}: # (2. Betriebsrentenstärkungsgesetz) -> Betriebsrentenstärkungsgesetz
        abbreviation_start += 1
    abbreviation_start = max(abbreviation_start, titel.find("- und ", abbreviation_start, len(titel) - 1) + len("- und ")) # (NIS-2-Umsetzungs- und Cybersicherheitsstärkungsgesetz) -> Cybersicherheitsstärkungsgesetz
    abbreviation_end = titel.find(" - ", abbreviation_start, len(titel) - 1) if titel.find(" - ", abbreviation_start, len(titel) - 1) > 0 else len(titel) - 1 # (Sportfördergesetz - SpoFöG) -> Sportfördergesetz
    abbreviation_end = titel.find(" – ", abbreviation_start, len(titel) - 1) if titel.find(" – ", abbreviation_start, len(titel) - 1) > 0 else len(titel) - 1 # same thing, except with long dash
    abbreviation = f"{titel[abbreviation_start:abbreviation_end]}*"
    return abbreviation

def query_from_spacy(titel, nlp):
    # This function is no longer needed, as extract_abbreviation + AI query generation yields superior results
    synonyms = {"Strafgesetzbuch*": "(Strafgesetzbuch* | StGB)",
        "Sozialgesetzbuch*": "(Sozialgesetzbuch* | SGB)",
        "Strafprozessordnung*": "(Strafprozessordnung | StPO)",
        "EU*": "(EU* | Europäische* Union)",
        "Union*": "(EU* | Europäische* Union)",
        "Rat*": "(EU* | Europäische* Rat*)",
        "Parlament*": "(EU* | Europäische* Parlament*)",
        }
    ignore = {"Änderung", "Vorschrift", "Einführung", "Umsetzung", "Deutschland", "Bundesrepublik",
     "Rat", "Regierung", "Republik", "Regelung", "§", "Buch", "Vermeidung", "Regelung", 
     "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember", 
     "Protokoll", "Errichtung", "Steuer", "Gebiet", "Maßnahme", "Einkommen", "Neuregelung", "Person", "Haushaltsjahr", "Mitgliedstaat", 
     "Bereich", "Vermögen", "Zusammenhang", "Zusammenarbeit", "Jahr", "Rahmenbedingung", "Weiterentwicklung", "Sicherstellung", "Bestimmung", "Ausgestaltung", "Artikel", 
     "Bezug", } 
    law_alternatives = {"Richtlinie", "Verordnung", "Übereinkommen", "Abkommen"}
    word = ""
    words = []
    doc = nlp(titel)
    
    for token in doc:
        if token.pos_ in {"NOUN", "PROPN"} and token.lemma_ not in ignore:
            # "Aufenthalt von Drittstaatsangehörigen" -> "Drittstaatsangehörige*", BUT "Vermeidung von Erzeugungsüberschüssen" -> "Erzeugungsüberschüsse", not "Erzeugungsüberschuss"
            word = f"{token.text[:-1]}*" if "Number=Plur" in token.morph and "Case=Dat" in token.morph and not token.text.startswith(token.lemma_) else f"{token.lemma_}*" 
        elif (offset := token.lemma_.find("rechtlich")) > 0:
            if token.lemma_[offset - 1] == 's': # versicherungSrechtlich
                offset -= 1
            word = f"({token.lemma_[0].lower()}{token.lemma_[1:offset]}* | {token.lemma_[0].upper()}{token.lemma_[1:offset]}*)" # (versicherung* | Versicherung*)

        if word:
            if word in synonyms:
                word = synonyms[word]

            if word not in words:
                words.append(word)
    
    if any(word in words for word in law_alternatives) and "Gesetz" in words:
        words.remove("Gesetz")

    return " + ".join(word for word in words)

def get_structured_data_from_ai(client, messages, schema=None, subfield=None):
    models = ['deepseek/deepseek-r1', 'deepseek/deepseek-chat', 'openai/gpt-4o-2024-11-20']

    # Openrouter models parameter is supposed to pass the query on to the next model if the first one fails, but currently only works for some types of errors, so we manually iterate
    for i, model in enumerate(models):
        response = client.chat.completions.create(model=model,
                                                    extra_body={
                                                        'models': models[i+1:],
                                                        'provider': {'require_parameters': True,
                                                                        'sort': 'throughput'},
                                                        'temperature': 0.5},
                                                        messages=messages, 
                                                        response_format={'type': 'json_schema', 
                                                                        'json_schema': schema})
        if response.choices:
            break

    if not response.choices or not response.choices[0].message.content:
        print(f"Error getting response from AI with messages: {messages}")
        return None
    
    ai_response = response.choices[0].message.content
    ai_response = re.sub(r"<think>.*?</think>", "", ai_response, flags=re.DOTALL)
    ai_response = re.sub(r"```json\n(.*?)\n```", r"\1", ai_response, flags=re.DOTALL)
    
    try:
        ai_response = json.loads(ai_response).get(subfield, None) if subfield else json.loads(ai_response)
        return ai_response
    except Exception as e:
        print(f"Could not parse AI response {ai_response}\nFrom: {response.choices[0].message.content}\n\n Error: {e}")
        return None
        

def get_text_data_from_ai(client, messages):
    models = ['deepseek/deepseek-r1', 'deepseek/deepseek-chat', 'openai/gpt-4o-2024-11-20']
    
    # Openrouter models parameter is supposed to pass the query on to the next model if the first one fails, but currently only works for some types of errors, so we manually iterate
    for i, model in enumerate(models):
        response = client.chat.completions.create(model=model, 
                                                    extra_body={
                                                        'models': models[i+1:],
                                                        'provider': {'sort': 'throughput'},
                                                        'temperature': 0.5},
                                                        messages=messages)
        if response.choices:
            break

    if not response.choices or not response.choices[0].message.content:
        print(f"Error getting response from AI with messages: {messages}")
        return None

    ai_response = response.choices[0].message.content

    # this shouldn't be necessary, but just in case
    ai_response = re.sub(r"<think>.*?</think>", "", ai_response, flags=re.DOTALL)
    ai_response = re.sub(r"```json\n(.*?)\n```", r"\1", ai_response, flags=re.DOTALL)
    return ai_response
    
@app.route("/bla")
def bla(law=None, infos=None):
    SUMMARY_LENGTH = 700
    IDEAL_ARTICLE_COUNT = 5
    MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY = 3
    MINIMUM_ARTICLE_LENGTH = 3500
    MAXIMUM_ARTICLE_LENGTH = 20000
    AI_API_KEY = os.environ.get("OPENROUTER_API_KEY")
    AI_ENDPOINT = "https://openrouter.ai/api/v1"

    # class Zeitraum(BaseModel):
    #     zusammenfassung: str = Field(strict=True, description="Die von dir erstellte Zusammenfassung.")

    # class Zeitraeume(BaseModel):
    #     zeitraeume: list[Zeitraum] = Field(strict=True, description="Die Liste der von dir erstellten Zusammenfassungen.")

    # class Suchergebnis(BaseModel):
    #     index: int = Field(strict=True, description="Der Index des Nachrichtenartikels in der Liste der Nachrichtenartikel, die du erhalten hast.")
    #     passend: int = Field(strict=True, description="Eine 1, wenn der Nachrichtenartikel sich auf das im system prompt erwähnte Gesetz bezieht, und eine 0, wenn nicht.")
    
    # class Suchergebnisse(BaseModel):
    #     suchergebnisse: list[Suchergebnis] = Field(strict=True, description="Die Liste der von dir als passend oder unpassend bewerteten Suchergebnisse.")

    # class Suchanfrage(BaseModel):
    #     suchanfrage: str = Field(strict=True, description="Eine der von dir generierten Suchanfragen.") 

    # class Suchanfragen(BaseModel):
    #     suchanfragen: list[Suchanfrage] = Field(strict=True, description="Die Liste der 3 von dir erstellten Suchanfragen.")

    
    client = OpenAI(base_url=AI_ENDPOINT, api_key=AI_API_KEY)
    gn = GNews(language='de', country='DE')

    abbreviation = extract_abbreviation(law.titel) if law.titel.endswith(")") else ""
    queries = []

    search_queries_schema = {
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
                        "description": "Eine von dir generierte Suchanfrage"
                    }
                }
            },
            "required": ["suchanfragen"]
        }
    }
    generate_search_queries_messages = [
        {
            "content": f"""Du erhältst vom Nutzer den amtlichen Titel eines deutschen Gesetzes. Dieser ist oft sperrig und klingt nach Behördensprache. 
            Überlege zunächst, mit welchen Begriffen in Nachrichtenartikeln vermutlich auf dieses Gesetz Bezug genommen wird. 
            Generiere dann 3 Suchanfragen zum Suchen nach Nachrichtenartieln über das Gesetz.
            Hänge an jedes Wort innerhalb der einzelnen Suchanfragen ein * an. Verwende niemals Worte wie 'Nachricht' oder 'Meldung', die kenntlich machen sollen, dass nach Nachrichtenartikeln gesucht wird.  
            Achte darauf, die einzelnen Suchanfragen nicht so restriktiv zu machen, dass relevante Nachrichtenartikel nicht gefunden werden. 
            Wenn es dir beispielsweise gelingt, ein einzelnes Wort zu finden, das so passend und spezifisch ist, dass es höchstwahrscheinlich nur in Nachrichtenartikeln vorkommt, die auch tatsächlich von dem Gesetz handeln, dann solltest du dieses Wort nicht noch um weitere Worte ergänzen, sondern allein als eine der Suchanfragen verwenden. 
            Deine Antwort MUSS ausschließlich aus JSON Daten bestehen und folgende Struktur haben:
            {json.dumps(search_queries_schema)}
            """,
            "role": "system"
        },
        {
            "content": law.titel,
            "role": "user"
        }
    ]
    
    try:
        ai_response = get_structured_data_from_ai(client, generate_search_queries_messages, search_queries_schema, "suchanfragen")
        queries = [query for query in ai_response if query]

    except Exception as e:
        print(f"Error generating search query.\nError: {e}\nAI response: {ai_response}")
        return infos
    
    if abbreviation and abbreviation not in queries:
        queries.insert(0, abbreviation)
    
    i = 0
    news_infos = []
    while i < len(infos):
        if infos[i].get("datum", None) is None: # position is in the future
            break

        start_date = datetime.datetime.strptime(infos[i]["datum"], "%d. %B %Y")
        news_info = {"index": i, "start": infos[i]['ai_info'], "artikel": [], "article_data": []}

        if i == len(infos) - 1 or infos[i + 1].get("datum", None) is None:
            end_date = datetime.datetime.now()
            news_info["end"] = "Das Ereignis, das den Start dieses Zeitraums markiert, ist der (bislang) letzte Schritt im Gesetzgebungsverfahren. Der Zeitraum, aus dem die mit diesem Zeitraum verknüpften Nachrichtenartikel stammen, reicht somit bis zum heutigen Tag."
        else:
            end_date = datetime.datetime.strptime(infos[i + 1]["datum"], "%d. %B %Y") # - datetime.timedelta(days=1)
            news_info["end"] = infos[i + 1]['ai_info']

        if start_date == end_date: # don't need news summary between two events on the same day
            i += 1
            continue

        gn.start_date = (start_date.year, start_date.month, start_date.day)
        gn.end_date = (end_date.year, end_date.month, end_date.day)

        for query in queries:
            if len(news_info["artikel"]) >= IDEAL_ARTICLE_COUNT:
                break
            
            try:
                if not (gnews_response := gn.get_news(query)):
                    raise Exception("did not get a response from gnews")
            except Exception as e:
                print(f"Error fetching news from gnews for query: {query}\nError: {e}\start date: {gn.start_date}\nend date: {gn.end_date}")
                continue

            try:
                evaluate_results_schema = {
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
                                            "description": "Die Indexnummer eines Artikels"
                                        },
                                        "passend": {
                                            "type": "number",
                                            "description": "1, wenn der Artikel mit dieser Indexnummer zum Gesetz passt, andernfalls 0"
                                        }
                                    },
                                    "required": ["index", "passend"]
                                }
                            }
                        },
                        "required": ["artikel"]
                    }
                }
                evaluate_results_messages = [
                    {
                        "content": f"""Du erhältst vom Nutzer eine Liste von strukturierten Daten. 
                        Jeder Eintrag in der Liste besteht aus einer Indexnummer und der Überschrift eines Nachrichtenartikels, die Nachricht des Nutzers wird also folgende Struktur haben: 
                        [{{'index': '1', 'titel': 'Ueberschrift_des_ersten_Nachrichtenartikels'}}, {{'index': '2', 'titel': 'Ueberschrift_des_zweiten_Nachrichtenartikels'}}, etc]. 
                        Deine Aufgabe ist es, für jeden Eintrag anhand der Überschrift zu prüfen, ob der Nachrichtenartikel sich auf das deutsche Gesetz mit dem amtlichen Titel '{law.titel}' bezieht, oder nicht. 
                        Dementsprechend wirst du in das Feld 'passend' in deiner Antwort entweder eine 1 (wenn der Nachrichtenartikel sich auf das Gesetz bezieht) oder eine 0 (wenn der Nachrichtenartikel sich nicht auf das Gesetz bezieht) eintragen.
                        Deine Antwort wird ausschließlich aus JSON Daten bestehen und folgende Struktur haben: {json.dumps(evaluate_results_schema)}""",
                        "role": "system"
                    },
                    {
                        "content": json.dumps([{'index': j, 'titel': article["title"]} for j, article in enumerate(gnews_response)], ensure_ascii=False),
                        "role": "user"
                    }
                ]
                ai_response = get_structured_data_from_ai(client, evaluate_results_messages, evaluate_results_schema, "artikel")

                for j in range(len(gnews_response) - 1, -1, -1):
                    if ai_response[j]["passend"] in {0, '0'}:
                        gnews_response.pop(j)

            except Exception as e:
                print(f"Error evaluating search results: {e}\nAI Response: {ai_response}")
                continue
                
            for article in gnews_response:
                if len(news_info["artikel"]) >= IDEAL_ARTICLE_COUNT:
                    break
                
                try:
                    url = gnewsdecoder(article["url"], 3)
                    if url["status"]:
                        article["url"] = url["decoded_url"]
                    else:
                        print(f"Error decoding URL of {article}")
                        continue  
                except Exception as e:
                    print(f"Unknown Error while decoding URL of {article}")
                    continue 

                try:
                    news_article = newspaper.article(article["url"], language='de')
                    news_article.download()
                    news_article.parse()
                except Exception as e:
                    print(f"Error parsing news article: {e}\nNews Article: {news_article}")
                    continue

                if not news_article.is_valid_body() or len(news_article.text) < MINIMUM_ARTICLE_LENGTH or len(news_article.text) > MAXIMUM_ARTICLE_LENGTH:
                    print(f"Article too long or too short at {len(news_article.text)} characters.")
                    continue
                
                # sometimes articles that got updated later are included in the response from Google News. This filters out some of those, though still not all.
                if not news_article.publish_date or news_article.publish_date.replace(tzinfo=None) >= end_date:
                    print(f"News article {news_article} ignored due to invalid publish date")
                    continue

                news_info["artikel"].append(news_article.text)
                news_info["article_data"].append(article)

        news_infos.append(news_info)
        i += 1

    # can't submit all intervals / articles in one message, or DeepSeek-R1 will get the timelines mixed up
    for news_info in news_infos:
        if len(news_info["artikel"]) < MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY:
            continue

        generate_summary_messages = [
            {
                "content": f"""Du erhältst vom Nutzer Angaben zu einem Zeitraum innerhalb des Gesetzgebungsverfahrens für das deutsche Gesetz mit dem amtlichen Titel {law.titel}. 
                Der Nutzer schickt dir das Ereignis, das am Anfang des Zeitraums steht, das Ereignis, das unmittelbar nach dem Ende des Zeitraums eintreten wird, und eine Liste von Nachrichtenartikeln, die innerhalb des Zeitraums erschienen sind.
                Die Nachricht des Nutzers wird also folgendes Format haben:
                'start': 'Die Bundesregierung bringt den Gesetzentwurf in den Bundestag ein', 'end': 'Die 1. Lesung im Bundestag findet statt.', 'artikel': ['Nachrichtenartikel 1', 'Nachrichtenartikel 2', etc]
                
                Du musst diese Nachricht in zwei Phasen bearbeiten.
                PHASE 1:
                Zunächst sollst du alle Nachrichtenartikel überprüfen. Falls ein Nachrichtenartikel sich nicht auf das Gesetz bezieht, oder nicht zu dem vom Nutzer angegebenen Zeitraum passt, MUSST DU IHN IGNORIEREN.
                Beachte dabei folgendes: Das Ereignis, das im Feld 'end' eines jeden Zeitabschnitts genannt wird, ist **in dem jeweiligen Zeitabschnitt noch nicht passiert**, sondern passiert erst unmittelbar nach diesem Zeitabschnitt. (Es sei denn, der Wert im Feld end lautet: 'Das Ereignis, das den Start dieses Zeitraums markiert, ist der (bislang) letzte Schritt im Gesetzgebungsverfahren. Der Zeitraum, aus dem die mit diesem Zeitraum verknüpften Nachrichtenartikel stammen, reicht somit bis zum heutigen Tag.'.)
                Wenn ein Zeitabschnitt also zum Beispiel end = "Die Beratung und Abstimmung im Bundesrat finden statt" hat, und mit diesem Zeitraum ein Nachrichtenartikel verknüpft ist, in dem steht, dass die Abstimmung im Bundesrat schon stattgefunden habe, dann ist dieser Nachrichtenartikel irrtümlich in die Liste der Artikel für diesen Zeitraum geraten, und **muss beim Erstellen der Zusammenfassung für diesen Zeitraum ignoriert werden**.
                
                PHASE 2:
                Wenn du entschieden hast, ob und gegebenenfalls welche Nachrichtenartikel du ignorieren musst, sollst du eine Zusammenfassung der wichtigsten und interessantesten Inhalte der übrigen Nachrichtenartikel erstellen.
                Wichtige / interessante nachrichtliche Inhalte sind zum Beispiel: Lob und Kritik zu dem Gesetz, die politische und mediale Auseinandersetzung mit dem Gesetz, Besonderheiten des Gesetzgebungsverfahrens, Klagen gegen das Gesetz, Stellungnahmen von durch das Gesetz betroffenen Personen oder Verbänden sowie einzelne, besonders im Fokus stehende Passagen des Gesetzes. 
                Weniger interessant ist hingegen eine neutrale Schilderung der wesentlichen Inhalte des Gesetzes - diese sollte in die Zusammenfassung nur aufgenommen werden, wenn sich aus den Nachrichtenartikeln nichts anderes, interessantes ergibt.            
                Einleitende Formulierungen wie "Im ersten Zeitraum" oder "In diesem Zeitraum" am Anfang der Zusammenfassung sollst du vermeiden. Du sollst aber auf das Ereignis Bezug nehmen, das den Start des jeweiligen Zeitraums markiert, sofern es in den Nachrichtenartikeln eine Rolle gespielt hat. 
                Die Zusammenfassung muss mindestens {SUMMARY_LENGTH - 100} und darf höchstens {SUMMARY_LENGTH + 100} Zeichen lang sein.
                Deine Zusammenfassung soll im Präsens verfasst sein. 
                Deine Antwort muss aus reinem, unformatiertem Text bestehen und AUSSCHLIEßLICH die Zusammenfassung enthalten. 
                """,
                "role": "system"
            },
            {
                "content": json.dumps({'start': news_info["start"], 'end': news_info['end'], 'artikel': [artikel for artikel in news_info["artikel"]]}, ensure_ascii=False).replace("\\n", "\n").replace('\\"', '"'),
                "role": "user"
            }
        ]

        if not (ai_response := get_text_data_from_ai(client, generate_summary_messages)):
            print(f"""Error getting summary for news info: {generate_summary_messages[1]["content"]}""")
            return infos

        news_info["zusammenfassung"] = ai_response


    offset = 0
    for i, news_info in enumerate(news_infos):
        if news_info.get("zusammenfassung", None):
            info = {"datum": start_date.strftime("%d. %B %Y"), 
                    "vorgangsposition": "Nachrichtenartikel",
                    "text": news_info["zusammenfassung"]}
            infos.insert(int(news_info.get("index", i)) + offset + 1, info) 
            offset += 1

    return infos


@app.route('/', methods=["GET", "POST"])
@app.route('/index')
def index():
    return render_template("index.html")

@app.route('/submit/<law_titel>', methods=["GET"])
def submit(law_titel):

    law_id = request.args.get('id')
    if not law_id or not (law := get_law_by_id(law_id)):
        return render_template("error.html")

    # ------------------ Phase 0: Gather preliminary information ----------------- #

    nachtraege = db.session.execute(db.select(Vorgangsposition.vorgangsposition, Fundstelle.pdf_url).filter(
    Fundstelle.positions_id == Vorgangsposition.id, Vorgangsposition.vorgangs_id == law.id,
    Vorgangsposition.nachtrag == True)).all()
    nachtraege = [{"vorgangsposition": v, "pdf_url": p} for v, p in nachtraege]

    beratungsstand = law.beratungsstand[-1] if law.beratungsstand else "Zu diesem Gesetz liegt leider noch kein Beratungsstand vor."
    law_abstract = law.abstract if law.abstract else "Zu diesem Gesetz liegt leider noch keine Zusammenfassung vor."
    zustimmungsbeduerftigkeit = ["<strong>Ja</strong>" + z[2:] if z.startswith("Ja") else "<strong>Nein</strong>" + z[4:] for z in law.zustimmungsbeduerftigkeit] \
        if law.zustimmungsbeduerftigkeit else "Zur Zustimmungsbedürftigkeit dieses Gesetzes liegen leider noch keine Zusammenfassung vor."
    zustimmungsbeduerftig = False if any("Nein" in z for z in law.zustimmungsbeduerftigkeit) else True # bei widerspruch setzen sich BRg / BT wohl durch. Falls das Nein vom BR kommt, eh egal.
    va_angerufen = False
   
    initiative = "Bundestag" if not law.initiative or not law.initiative[0] or "Fraktion" in law.initiative[0] \
    or "Gruppe" in law.initiative[0] or "ausschuss" in law.initiative[0].lower() \
    else "Bundesregierung" if law.initiative[0] == "Bundesregierung" \
    else "Bundesrat"  # law.initiative is None if a random group of Abgeordnete initiates the law, which effectively equates to "Bundestag"
    pfad = copy.deepcopy(pfade[initiative])

    law.vorgangspositionen.sort(key=lambda vp: vp.datum) # TODO: Find out why this is even necessary (in rare cases, like dip_id 315332)
    infos = []

    # ---- Phase I: Parse all Vorgangspositionen (what has happened thus far) ---- #
    for position in law.vorgangspositionen:
        
        if not position.gang:
            continue
            
        info = {"datum": position.datum.strftime("%d. %B %Y"),
                "vorgangsposition": position.vorgangsposition,
                "link": f'<a href="{position.fundstelle.pdf_url}">Originaldokument</a>',
                "ai_info": "",
                "has_happened": True,
                "passed": True,
                "marks_failure": False,
                "marks_success": False}
        
        for nachtrag in nachtraege:
            if nachtrag["vorgangsposition"] == position.vorgangsposition:
                info["link"] += f', <a href="{nachtrag["pdf_url"]}">Nachtrag</a>'

        match position.vorgangsposition:

            case 'Gesetzentwurf':
                if position.urheber_titel:
                    text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                    text += " legt" if len(position.urheber_titel) == 1 else " legen"
                    text += f" dem {zuordnungen[position.zuordnung]} den Gesetzentwurf vor."
                else:
                    text = f"Der Gesetzentwurf wird im {zuordnungen[position.zuordnung]} eingebracht."
                ai_info = text
                info["vorgangsposition"] = "Gesetzentwurf im Bundestag" if position.zuordnung == "BT" else "Gesetzentwurf im Bundesrat"

            case "1. Beratung" | "Zurückverweisung an die Ausschüsse in 2./3. Beratung":
                ausschuesse = sorted(
                    [ueberweisung.ausschuss + " (federführend)" if ueberweisung.federfuehrung \
                     else ueberweisung.ausschuss for ueberweisung in position.ueberweisungen],
                     key=lambda x: " (federführend)" not in x)
                
                ausschuesse = parse_actors(ausschuesse, praepositionen_akkusativ, iterable=True)
                if position.vorgangsposition == "1. Beratung":
                    text = "Die 1. Lesung im Bundestag findet statt. Das Gesetz wird überwiesen an\n\n<ul>" 
                    ai_info = "Die 1. Lesung im Bundestag findet statt."
                else:
                    text = "Das Gesetz wird in der 2./3. Lesung zurückverwiesen an\n\n<ul>"
                    ai_info = "Das Gesetz wird in der 2./3. Lesung zurückverwiesen."

                for ausschuss in ausschuesse:
                    text += f"<li>{ausschuss}</li>"
                text += "</ul>"

                # if Zurückverweisung, reset passed Flag on previous Beschlussempfehlung
                if position.vorgangsposition == "Zurückverweisung an die Ausschüsse in 2./3. Beratung":
                    for inf in infos:
                        if inf["vorgangsposition"] in ["Beschlussempfehlung und Bericht", "Beschlussempfehlung"]:
                            inf["passed"] = False

                # TODO: Possibility of "Zusammengeführt mit" here, like in 2. / 3. Beratung?

            case "Beschlussempfehlung und Bericht" | "Beschlussempfehlung":
                text = parse_actors(position.urheber_titel, praepositionen_genitiv)
                abstract = position.abstract[12:] if position.abstract.startswith("Empfehlung: ") else position.abstract
                text = "Die Empfehlung " + text + f" lautet: \n<strong>{abstract}</strong>."
                ai_info = text

            case "Bericht":
                text = parse_actors(position.urheber_titel, praepositionen_genitiv)
                text = "Der Bericht " + text + " liegt vor."
                ai_info = text

            case "2. Beratung" | "2. Beratung und Schlussabstimmung":                
                if position.abstract and position.abstract.startswith("Zusammengeführt mit"):
                    info["marks_failure"] = True
                    text = create_link(position)

                elif (beschluesse_dritte_beratung := db.session.query(Beschlussfassung).filter(
                    Beschlussfassung.positions_id == Vorgangsposition.id, Vorgangsposition.vorgangs_id == law.id, 
                    Vorgangsposition.vorgangsposition == "3. Beratung", Vorgangsposition.nachtrag == False, Vorgangsposition.datum == position.datum).all()):

                    # some modifications to info because we are merging two vorgangspositionen into one
                    info["vorgangsposition"] = "2. und 3. Beratung"
                    for nachtrag in nachtraege:
                        if nachtrag["vorgangsposition"] == "3. Beratung":
                            info["link"] += f', <a href="{nachtrag["pdf_url"]}">Nachtrag</a>'
    
                    ai_info = text = "Die 2. und 3. Lesung im Bundestag finden am selben Tag statt."

                    position_beschluesse = copy.deepcopy(position.beschluesse)
                    beschluesse_dritte_beratung = copy.deepcopy(beschluesse_dritte_beratung)
                    position_beschluesse.extend(beschluesse_dritte_beratung)
                    gemeinsame_beschluesse = merge_beschluesse(position_beschluesse,
                                                    {position.id : position.vorgangsposition,
                                                     beschluesse_dritte_beratung[0].positions_id : "3. Beratung"}, needs_copy=False)
                    
                    text += f" Die Beschlüsse des Bundestags werden nachfolgend gemeinsam dargestellt, sofern sie in beiden Beratungen gleich lauten, andernfalls getrennt: \n\n"
                    text += "".join(parse_beschluesse(law, gemeinsame_beschluesse[k]) if gemeinsame_beschluesse[k] and k == "2. und 3. Beratung" \
                        else f"<u>Nur {k}:</u> {parse_beschluesse(law, gemeinsame_beschluesse[k])}" if gemeinsame_beschluesse[k] else "" \
                            for k in ["2. und 3. Beratung", "2. Beratung", "3. Beratung"])  
                    
                else:
                    beschluesse = merge_beschluesse(position.beschluesse) if len(position.beschluesse) > 1 else position.beschluesse
                    ai_info = text = "Die 2. Lesung im Bundestag findet statt." if position.vorgangsposition == "2. Beratung" else \
                    "Die 2. Lesung und Schlussabstimmung im Bundestag findet statt."
                    text += " Der Beschluss des Bundestags lautet: \n\n" if len(beschluesse) == 1 else \
                    " Die Beschlüsse des Bundestags lauten: \n\n"
                    text += parse_beschluesse(law, beschluesse)
                
                for beschluss in position.beschluesse:
                    if beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit":
                        info["passed"] = False
                    if beschluss.beschlusstenor in ["Ablehnung der Vorlage", "Ablehnung der Vorlagen"]: 
                        info["marks_failure"] = True
                        text += "\n\nDamit ist das Gesetz gescheitert."

            case "3. Beratung":
                daten_zweite_beratung = db.session.execute(db.select(Vorgangsposition.datum).filter(Vorgangsposition.vorgangs_id == law.id, Vorgangsposition.nachtrag == False,
                                        or_(Vorgangsposition.vorgangsposition == "2. Beratung", Vorgangsposition.vorgangsposition == "2. Beratung und Schlussabstimmung"))).scalars().all()
                
                if any(datum == position.datum for datum in daten_zweite_beratung):
                    continue
                
                if position.abstract and position.abstract.startswith("Zusammengeführt mit"):
                    info["marks_failure"] = True
                    text = create_link(position)
                else:
                    beschluesse = merge_beschluesse(position.beschluesse)
                    ai_info = text = "Die 3. Lesung im Bundestag findet statt."
                    text += " Der Beschluss des Bundestags lautet: \n\n" if len(beschluesse) == 1 else " Die Beschlüsse des Bundestags lauten: \n\n"
                    text += parse_beschluesse(law, beschluesse)

                    for beschluss in position.beschluesse:
                        if beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit":
                            info["passed"] = False
                        if beschluss.beschlusstenor in ["Ablehnung der Vorlage", "Ablehnung der Vorlagen"]: 
                            info["marks_failure"] = True

            case "1. Durchgang": 
                ai_info = text = "Der 1. Durchgang im Bundesrat findet statt."
                beschluesse = merge_beschluesse(position.beschluesse)
                text += " Der Beschluss des Bundesrats lautet: \n\n" if len(beschluesse) == 1 else " Die Beschlüsse des Bundesrats lauten: \n\n"
                text += parse_beschluesse(law, beschluesse)

                if any(beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit" for beschluss in beschluesse):
                    info["passed"] = False

            case "2. Durchgang" | "Durchgang": # Durchgang, wenn initiative = Bundestag, weil es dann keinen 1. Durchgang gab
                ai_info = text = "Die Beratung und Abstimmung im Bundesrat finden statt."
                info["vorgangsposition"] = "Abstimmung im Bundesrat"                
                
                beschluesse = merge_beschluesse(position.beschluesse)
                text += " Der Beschluss des Bundesrats lautet: \n\n" if len(beschluesse) == 1 else " Die Beschlüsse des Bundesrats lauten: \n\n"
                text += parse_beschluesse(law, beschluesse)

                for beschluss in beschluesse:
                    if beschluss.beschlusstenor.startswith("kein Antrag auf Einberufung des Vermittlungsausschusses") or beschluss.beschlusstenor.startswith("Zustimmung"):
                        text += "\n\nDamit hat das Gesetz alle Hürden genommen. Das Gesetzgebungsverfahren ist erfolgreich beendet."
                        info["marks_success"] = True

                    # BT-Sitzung nach Vermittlungsvorschlag offenbar nicht unbedingt nötig, jedenfalls nicht wenn nicht zustimmungsbedürftig, vgl
                    # https://search.dip.bundestag.de/api/v1/vorgangsposition?f.vorgang=303742&apikey=I9FKdCn.hbfefNWCY336dL6x62vfwNKpoN2RZ1gp21

                    # We still pass this stage if va is called, as further sessions of the BR will be BR-Sitzung, not Durchgang / 2. Durchgang
                    if beschluss.beschlusstenor.startswith("Anrufung des Vermittlungsausschusses"):
                        va_angerufen = True
                        pfad.append(copy.deepcopy(abstimmung_ueber_va_vorschlag_im_br))
                                            
                    if beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit":
                        info["passed"] = False

            case "Gesetzesantrag":
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += " beantragt," if len(position.urheber_titel) == 1 else " beantragen,"
                text += " der Bundesrat möge beschließen, das Gesetz im Bundestag einzubringen."
                ai_info = text

            case "Plenarantrag":
                text = "Im Plenum " + parse_actors(zuordnungen[position.zuordnung], praepositionen_genitiv)
                text += f" wird folgender Antrag gestellt: \n\n<strong>{position.abstract}</strong>."
                ai_info = text

            case "BR-Sitzung": # kommt bei initiative von Land (typischerweise 2x) oder bei ini von BT/BRg (nach Anrufung d. Vermittlungsausschusses)
                beschluesse = merge_beschluesse(position.beschluesse)
                text = "Der Bundesrat befasst sich mit dem Gesetz und beschließt:\n\n"
                text += parse_beschluesse(law, beschluesse)
                ai_info = "Beschlussfassung zu dem Gesetz im Bundesrat."

                gebilligt = False
                einspruch = True

                for beschluss in beschluesse:
                    if initiative == "Bundesrat" and beschluss.beschlusstenor in ["Ablehnung der Einbringung", "Ablehnung der erneuten Einbringung", "für erledigt erklärt"]:
                        text += "\n\nDamit ist das Gesetz gescheitert; das Gesetzgebungsverfahren ist am Ende."
                        info["passed"] = False
                        info["marks_failure"] = True
                    
                    if initiative == "Bundesrat" and not (beschluss.beschlusstenor.startswith("Einbringung") or beschluss.beschlusstenor.startswith("erneute Einbringung")): # postponement etc
                        info["passed"] = False      

                    if va_angerufen:
                        if zustimmungsbeduerftig:
                            if "Versagung der Zustimmung" in beschluss.beschlusstenor:
                                text += "\n\nDamit ist das Gesetz gescheitert; das Gesetzgebungsverfahren ist am Ende."
                                info["passed"] = False
                                info["marks_failure"] = True
                            elif "Zustimmung" in beschluss.beschlusstenor:
                                gebilligt = True
                                text += "\n\nDamit hat das Gesetz alle Hürden genommen. Das Gesetzgebungsverfahren ist erfolgreich beendet."
                                info["marks_success"] = True
                        else:
                            if "kein Einspruch" in beschluss.beschlusstenor:
                                einspruch = False
                                text += "\n\nDamit hat das Gesetz alle Hürden genommen. Das Gesetzgebungsverfahren ist erfolgreich beendet."
                                info["marks_success"] = True
                            elif "Einspruch" in beschluss.beschlusstenor: # speculating, need example
                                einspruch = True
                                pfad.append(copy.deepcopy(ueberstimmung_des_br_bei_einspruchsgesetz))

                # Most likely, if either of these conditions trigger, passes is already False and the law has failed. 
                # But, maybe, the Beschlüsse were just formal stuff / a postponement so that another BR-Sitzung is coming.
                if va_angerufen and zustimmungsbeduerftig and not gebilligt:
                    info["passed"] = False
                if va_angerufen and not zustimmungsbeduerftig and not einspruch:
                    info["passed"] = False
                 
            case "Berichtigung zum Gesetzesbeschluss":
                ai_info = text = f"Im {zuordnungen[position.zuordnung]} wird eine Berichtigung (meist eine Korrektur redaktioneller Fehler) beschlossen."

            # case "...BR" included only as a fallback, likely won't match for the BR as gang tends to be False, VA-Anrufung by BR is instead handled in Durchgang.
            case "Unterrichtung über Anrufung des Vermittlungsausschusses durch die BRg" | "Unterrichtung über Anrufung des Vermittlungsausschusses durch den BR":
                info["vorgangsposition"] = "Unterrichtung über Anrufung des Vermittlungsausschusses durch die Bundesregierung" if position.vorgangsposition.endswith("BRg") \
                else "Unterrichtung über Anrufung des Vermittlungsausschusses durch den Bundesrat" 
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" unterrichtet den {zuordnungen[position.zuordnung]} darüber, dass sie den Vermittlungsausschuss angerufen hat."
                ai_info = text
                va_angerufen = True

            case "Unterrichtung über Stellungnahme des BR und Gegenäußerung der BRg":
                info["vorgangsposition"] = "Unterrichtung über Stellungnahme des Bundesrats und Gegenäußerung der Bundesregierung"
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" unterrichtet den {zuordnungen[position.zuordnung]} über die Stellungnahme des Bundesrats und die Gegenäußerung der Bundesregierung."
                ai_info = text

            case "Unterrichtung über Zustimmungsversagung durch den BR":
                info["vorgangsposition"] = "Unterrichtung über Zustimmungsversagung durch den Bundesrat."
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" unterrichtet den {zuordnungen[position.zuordnung]} über die Zustimmungsversagung des Bundesrats."
                ai_info = text

            case "Vermittlungsvorschlag" | "Einigungsvorschlag":
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" legt dem {zuordnungen[position.zuordnung]} den {position.vorgangsposition} des Vermittlungsausschusses vor."
                ai_info = text
                abstract = position.abstract[12:] if position.abstract.startswith("Empfehlung: ") else position.abstract
                text += f" Seine Empfehlung lautet: \n<strong>{abstract}</strong>"

                if position.vorgangsposition == "Vermittlungsvorschlag":
                    pfad.append(copy.deepcopy(abstimmung_ueber_vermittlungsvorschlag_im_bt))

            case "Abstimmung über Vermittlungsvorschlag":
                text = f"Im {zuordnungen[position.zuordnung]} wird über den Vermittlungsvorschlag abgestimmt. Das Abstimmungsergebnis lautet: \n\n"
                ai_info = f"Im {zuordnungen[position.zuordnung]} wird über den Vermittlungsvorschlag abgestimmt."
                beschluesse = merge_beschluesse(position.beschluesse)
                text += parse_beschluesse(law, beschluesse)

                if not any(beschluss.beschlusstenor == "Annahme" for beschluss in beschluesse): # possibly refine with more examples?
                    info["passed"] = False
                    text += "\n\n Damit ist das Gesetz gescheitert. Das Gesetzgebungsverfahren ist am Ende."
                    info["marks_failure"] = True

            case "Protokollerklärung/Begleiterklärung zum Vermittlungsverfahren":
                abstract = position.abstract if position.abstract else ""
                ai_info = text = f"Im {zuordnungen[position.zuordnung]} wird eine Erklärung zum Vermittlungsverfahren abgegeben: {abstract}."

            case "Rücknahme der Vorlage" | "Rücknahme des Antrags":
                typ = "die Vorlage" if position.vorgangsposition == "Rücknahme der Vorlage" else "der Antrag"
                ai_info = text = f"Im {zuordnungen[position.zuordnung]} wird {typ} zurückgenommen. Damit ist das Gesetzgebungsverfahren beendet."
                info["marks_failure"] = True

            case "Unterrichtung":
                ai_info = text = f"Im {zuordnungen[position.zuordnung]} findet folgende Unterrichtung statt: \n{position.abstract}."

        info["text"] = text
        info["ai_info"] = ai_info
        infos.append(info)


    # -------------------- Phase 2: Check how far we have come ------------------- #
    # ------------------- add what remains to be done to infos ------------------- #

    # No need to process remaing if law has already failed or succeeded
    for info in infos:
        if info["marks_failure"]:
            infos = bla(law, infos) # TODO: remove
            return render_template("results.html", titel=law.titel, beratungsstand=beratungsstand, abstract=law_abstract, zustimmungsbeduerftigkeit=zustimmungsbeduerftigkeit, infos=infos)
        
        if info["marks_success"]:
            if beratungsstand == "Nicht ausgefertigt wegen Zustimmungsverweigerung des Bundespräsidenten":
                info["text"] += "\n\n<strong>Der Bundespräsident hat sich jedoch wegen verfassungsrechtlicher Bedenken geweigert, das Gesetz auszufertigen. Es wird somit nicht in Kraft treten</strong>."
                infos = bla(law, infos)
                return render_template("results.html", titel=law.titel, beratungsstand=beratungsstand, abstract=law_abstract, zustimmungsbeduerftigkeit=zustimmungsbeduerftigkeit, infos=infos)

            if law.verkuendung:
                for verkuendung in law.verkuendung:
                    info["text"] += f'\n\nDas Gesetz wurde <strong>am {verkuendung.verkuendungsdatum.strftime("%d. %B %Y")} verkündet</strong>'
                    info["text"] += f' (<a href="{verkuendung.pdf_url}">Link zur Verkündung</a>).' if verkuendung.pdf_url else "."
            else:
                info["text"] += "\n\nDas Gesetz <strong>muss allerdings noch verkündet werden, um in Kraft zu treten.</strong>"
            
            if law.inkrafttreten:
                for inkraft in law.inkrafttreten:
                    erlaeuterung = f" ({inkraft.erlaeuterung})" if inkraft.erlaeuterung else " "
                    info["text"] += f"\n\nDas Gesetz{erlaeuterung} ist <strong>am {inkraft.datum.strftime("%d. %B %Y")} in Kraft getreten</strong>." if inkraft.datum <= datetime.datetime.now().date() \
                        else f"\n\nDas Gesetz{erlaeuterung} <strong>wird am {inkraft.datum.strftime("%d. %B %Y")} in Kraft treten</strong>."
            else:
                info["text"] += "\n\nZum <strong>Datum des Inkrafttretens</strong> ist noch nichts bekannt."
            
            if beratungsstand in {"Teile des Gesetzes für nichtig erklärt", "Für nichtig erklärt", "Für mit dem Grundgesetz unvereinbar erklärt"}:
                entscheidung_bverfg = "teilweise für nichtig erklärt" if beratungsstand == "Teile des Gesetzes für nichtig erklärt" else "f" + beratungsstand[1:]
                info["text"] += f"\n\n<strong>Das Gesetz wurde durch das Bundesverfassungsgericht jedoch {entscheidung_bverfg}.</strong>"

    remaining = []
    used_info_indices = set()
    for station in pfad:
        found = False
        for i, info in enumerate(infos):
            if all(info.get(k) in v for k, v in station.items() if k != "text") and info["passed"] and i not in used_info_indices:
                used_info_indices.add(i)
                found = True
                break
        if not found:
            remaining.append(station)
    
    # Have to do this manually because 2. and 3. Beratung may or may not have been merged
    if zweite_und_dritte_beratung not in remaining:
        for b in [zweite_beratung, dritte_beratung]:
            if b in remaining:
                remaining.remove(b)
    else:
        remaining.remove(zweite_und_dritte_beratung)

    for station in remaining:
        station["has_happened"] = False
        # check for cases where I introduced ambiguity, currently only "Beschlussempfehlung und Bericht", may simplify later
        if type(station["vorgangsposition"]) == list and len(station["vorgangsposition"]) > 1: 
            station["vorgangsposition"] = station["vorgangsposition"][0]
        infos.append(station)
    
    infos = bla(law, infos)
    return render_template("results.html", titel=law.titel, beratungsstand=beratungsstand, abstract=law_abstract, zustimmungsbeduerftigkeit=zustimmungsbeduerftigkeit, infos=infos)

@app.route('/autocomplete')
def autocomplete():
    query = request.args.get('q', '').lower()
    if query == '':
        return jsonify([])
    
    response = es.search(index=ES_LAWS_INDEX, 
                         body={
                             'query': {
                                 'multi_match': {
                                     'query': query,
                                     'fields': ['titel^2', 'abstract'],
                                     'type': 'best_fields' # maybe experiment with most_fields or cross_fields, also maybe add 'fuzziness': 'AUTO'
                                 }
                             },
                             'size': 10
                         })
    suggestions = [{'id': hit['_id'], 'titel': hit['_source']['titel']} for hit in response['hits']['hits']]
    return jsonify(suggestions)
