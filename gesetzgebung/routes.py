import newspaper.configuration
from gesetzgebung.es_file import es, ES_LAWS_INDEX
from gesetzgebung.flask_file import app
from gesetzgebung.models import *
from gesetzgebung.helpers import *
from gesetzgebung.daily_update import daily_update
from flask import render_template, request, jsonify
import datetime
import copy
import requests
import re
import spacy
import os
import json
from openai import OpenAI
import newspaper
from gnews import GNews
from googlenewsdecoder import gnewsdecoder

THE_NEWS_API_KEY = 'lglEeSs4tfC3vW2IgkThxlmBrEk4e8YjZg1MnopQ'
THE_NEWS_API_TOP_STORIES_ENDPOINT = 'https://api.thenewsapi.com/v1/news/top'
THE_NEWS_API_ENDPOINT = 'https://api.thenewsapi.com/v1/news/all'

def extract_abbreviation(titel):
    parentheses_start = max(6, titel.rfind("(")) # There will never be a ( before index 6, max is just in case there is a ) without a ( in the title
    abbreviation_start = parentheses_start + 1
    while titel[abbreviation_start].isdigit() or titel[abbreviation_start] in {".", " "}: # (2. Betriebsrentenstärkungsgesetz) -> Betriebsrentenstärkungsgesetz
        abbreviation_start += 1
    abbreviation_start = max(abbreviation_start, titel.find("- und ", abbreviation_start, len(titel) - 1) + len("- und ")) # (NIS-2-Umsetzungs- und Cybersicherheitsstärkungsgesetz) -> Cybersicherheitsstärkungsgesetz
    abbreviation_end = titel.find(" - ", abbreviation_start, len(titel) - 1) if titel.find(" - ", abbreviation_start, len(titel) - 1) > 0 else len(titel) - 1 # (Sportfördergesetz - SpoFöG) -> Sportfördergesetz
    abbreviation_end = titel.find(" – ", abbreviation_start, len(titel) - 1) if titel.find(" – ", abbreviation_start, len(titel) - 1) > 0 else len(titel) - 1 # same thing, except with long dash
    abbreviation = f"{titel[abbreviation_start:abbreviation_end]}*"
    titel = titel[:parentheses_start - 1] # remove parentheses after processing them
    return (titel, abbreviation)

def query_from_spacy(titel, nlp):
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
            # "Aufenthalt von Drittstaatsangehörigen" -> "Drittstaatsangehörige*", ABER "Vermeidung von Erzeugungsüberschüssen" -> "Erzeugungsüberschüsse", nicht "Erzeugungsüberschuss"
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

@app.route("/blub")
def blub():
    newspaper.configuration.Configuration.MAX_SUMMARY = 3000
    newspaper.configuration.Configuration.MAX_SUMMARY_SENT = 10
    article = newspaper.article("https://www.tagesschau.de/inland/gesellschaft/selbstbestimmungsgesetz-112.html", language='de')
    nlp = spacy.load("de_core_news_sm") # or de_dep_news_trf
    doc = nlp(article.text)
    return f"########\nText:\n{article.text}\n\n###########Summary:\n{article.summary}\n"
    

@app.route("/bla")
def bla(law=None, infos=None):
    THE_NEWS_API_KEY = os.environ.get("THE_NEWS_API_KEY")
    THE_NEWS_API_ENDPOINT = 'https://api.thenewsapi.com/v1/news/all'
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
    ARTICLES_PER_REQUEST = 25
    IDEAL_SUMMARIES_COUNT = 10
    MAX_OVERALL_SUMMARY_LENGTH = 1000
    MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY = 3
    MAX_FALSE_HITS = 6
    RELEVANCE_CUTOFF = 10
    AI_TO_USE = "OpenAI"
    AI_API_KEY = os.environ.get("OPENAI_API_KEY") if AI_TO_USE == "OpenAI" else os.environ.get("DEEPSEEK_API_KEY") if AI_TO_USE == "DeepSeek" else None
    AI_GENERAL_PURPOSE_MODEL = "gpt-4o" if AI_TO_USE == "OpenAI" else "deepseek-chat" if AI_TO_USE == "DeepSeek" else None
    AI_REASONING_MODEL = "o1" if AI_TO_USE == "OpenAI" else "deepseek-reasoner" if AI_TO_USE == "DeepSeek" else None 

    system_prompt = """Du bist ein hilfreicher Assistent, der mir helfen soll, Suchbegriffe aus den amtlichen Titeln deutscher Gesetze zu generieren, und aus einer Reihe von Suchergebnissen eine Auswahl zu treffen und eine Zusammenfassung zu erstellen. 
    Meine Nachricht an dich beginnt entweder mit den Worten "SUCHANFRAGE GENERIEREN" (gefolgt vom Titel eines deutschen Gesetzes) oder "ZUSAMMENFASSUNG GENERIEREN" (gefolgt vom Titel eines Gesetzes und einer Reihe von Suchergebnissen). 

    Wenn meine Nachricht mit "SUCHANFRAGE GENERIEREN" beginnt, wirst du aus dem Titel des Gesetzes zwei unterschiedliche Suchanfragen generieren, um möglichst viele relevante Nachrichtenartikel zu dem Gesetz zu finden.
    Du wirst die drei Suchanfragen jeweils in Klammern setzen und durch ein | voneinander trennen. Außerdem wirst du an jedes Wort in den Suchanfragen ein * anhängen. Wenn mehrere Worte vorhanden sein müssen, wirst du das mit einem + kenntlich machen.
    Ein Beispiel für eine Suchanfrage zu einem Gesetz mit dem Titel "Gesetz über die Selbstbestimmung in Bezug auf den Geschlechtseintrag und zur Änderung weiterer Vorschriften" wäre: "(Selbstbestimmungsgesetz*) | (Gesetz* + Selbstbestimmung* + Geschlechtseintrag*)"

    Wenn meine Nachricht mit "ZUSAMMENFASSUNG GENERIEREN" beginnt, wirst du mir die Indexnummer desjenigen Suchergebnisses schicken, das am besten zu dem Gesetz passt. Wenn keines gut passt, wirst du mir die -1 als Indexnummer schicken.

    Du wirst AUSSCHLIEßLICH mit dem Suchbegriff bzw. der Indexnummer antworten.
    """  

    
    # nlp = spacy.load("de_core_news_sm") # or de_dep_news_trf
    
    # client = OpenAI(api_key=DEEPSEEK_API_KEY,base_url="https://api.deepseek.com")
    client = OpenAI(api_key=AI_API_KEY)
    gn = GNews(language='de', country='DE')
    # assistant = client.beta.assistants.retrieve("asst_qEHStCSjEx5Gya8xVGXbTYLO") or client.beta.assistants.create(name="Assistent_Nachrichtensuche", instructions=system_prompt, model="gpt-4o", temperature=0.5)
    # thread = client.beta.threads.create()

    titel : str = law.titel if law.titel else "Nicht vorhanden"
    titel, abbreviation = extract_abbreviation(titel) if titel.endswith(")") else (titel, "")
    queries = []

    generate_title_message = [
        {
            "content": "Du erhältst vom Nutzer den amtlichen Titel eines deutschen Gesetzes. Dieser ist oft sperrig und klingt nach Behördensprache. Überlege zunächst, mit welchen Begriffen in Nachrichtenartikeln vermutlich auf dieses Gesetz Bezug genommen wird. Generiere dann Suchanfragen zum Suchen nach Nachrichtenartieln über das Gesetz. Im Normalfall sollst du drei Suchanfragen generieren, du kannst aber auch nur eine oder zwei generieren, falls dir keine weiteren sinnvollen Suchanfragen einfallen. Jede Suchanfrage sollte aus einem oder mehreren Worten bestehen, die durch Leerzeichen getrennt sind. Die einzelnen Suchanfragen sollten durch ein ' | 'von einander getrennt sein. Hänge an jedes Wort innerhalb der einzelnen Suchanfragen ein * an. Verwende niemals Worte wie 'Nachricht' oder 'Meldung', die kenntlich machen sollen, dass nach Nachrichtenartikeln gesucht wird. Bedenke, dass die Begriffe innerhalb der einzelnen Suchanfragen automatisch mit UND verknüpft sind, die Suchanfragen selbst jedoch mit ODER verknüpft sind. Nutze also synonyme Begriffe wie 'Reform' oder 'Novelle' nicht innerhalb derselben Suchanfrage, sondern verteile sie über die Suchanfragen, um Nachrichtenartikel zu finden, die den einen oder den anderen Begriff verwenden. Achte darauf, die Suchanfragen restriktiv genug zu machen, damit möglichst wenige Nachrichtenartikel gefunden werden, die nichts mit dem Gesetz zu tun haben. Achte aber umgekehrt auch darauf, die Suchanfragen nicht so restriktiv zu machen, dass Nachrichtenartikel nicht gefunden werden, die sehr wohl etwas mit dem Gesetz zu tun haben. Wenn es dir beispielsweise gelingt, ein einzelnes Wort zu finden, das so passend und spezifisch ist, dass es höchstwahrscheinlich nur in Nachrichtenartikeln vorkommt, die auch tatsächlich von dem Gesetz handeln, dann solltest du dieses Wort nicht noch um weitere Worte ergänzen, sondern allein als eine der Suchanfragen verwenden. Antworte AUSSCHLIEßLICH mit den Suchanfragen.",
            "role": "system"
        },
        {
            "content": titel,
            "role": "user"
        }
    ]
    try:
        response = client.chat.completions.create(model=AI_REASONING_MODEL, messages=generate_title_message, temperature=0.7, stream=False)
        queries = [query for query in response.choices[0].message.content.split(" | ") if query]
    except Exception as e:
        try:
            print(f"Error generating search query with reasoning model, trying general purpose model. Error: {e}")
            response = client.chat.completions.create(model=AI_GENERAL_PURPOSE_MODEL, messages=generate_title_message, temperature=0.7, stream=False)
            queries = [query for query in response.choices[0].message.content.split(" | ") if query]
        except Exception as e2:
            print(f"Error generating search query with general purpose model. Error: {e}")
            return infos        
    
    if abbreviation and abbreviation not in queries:
        queries.insert(0, abbreviation)

    # try:
    #     message = client.beta.threads.messages.create(thread_id=thread.id, role="user", content=f"SUCHANFRAGE GENERIEREN\nGesetzestitel: {titel}")
    #     run = client.beta.threads.runs.create_and_poll(thread_id=thread.id, assistant_id=assistant.id)
        
    #     if run.status == "completed":
    #         messages = client.beta.threads.messages.list(thread_id=thread.id)
    #         query = messages.data[0].content[0].text.value
    #         query = f"{query} | ({abbreviation})" if abbreviation and f"({abbreviation})" not in query else query

    #         for message in messages.data:
    #             client.beta.threads.messages.delete(message_id=message.id, thread_id=thread.id)

    # except Exception as e:
    #     print(e)

    # params = {'api_token': THE_NEWS_API_KEY,     
    #     'search': query,
    #     'language': 'de',
    #     'page': 1,
    #     'limit': ARTICLES_PER_REQUEST,
    #     "published_after": dates[0].strftime("%Y-%m-%d"),
    #     "published_before": datetime.datetime.now().strftime("%Y-%m-%d")}
    

    # indices = []
    
    i = 0
    while i < len(infos):
        if infos[i].get("datum", None) is None:
            break
        start_date = datetime.datetime.strptime(infos[i]["datum"], "%d. %B %Y")

        if i == len(infos) - 1 or infos[i + 1].get("datum", None) is None:
            end_date = datetime.datetime.now()
        else:
            end_date = datetime.datetime.strptime(infos[i + 1]["datum"], "%d. %B %Y")

        if start_date == end_date:
            continue

    # for start_date, end_date in zip(dates, dates_shifted):
    #     if start_date == end_date:
    #         continue
        
        # start_date = start_date.strftime("%Y-%m-%d")
        # end_date = (end_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        # params["published_after"] = start_date.strftime("%Y-%m-%d") if i > 0 else (start_date - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        # params["published_before"] = (end_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d") 

        gn.start_date = (start_date.year, start_date.month, start_date.day)
        gn.end_date = (end_date.year, end_date.month, end_date.day)
        articles = []

        for query in queries:
            if len(articles) >= IDEAL_SUMMARIES_COUNT:
                break
            false_hits = 0 
            gnews_response = gn.get_news(query)

            for article in gnews_response:
                if len(articles) >= IDEAL_SUMMARIES_COUNT or false_hits >= MAX_FALSE_HITS:
                    break
                
                try:
                    url = gnewsdecoder(article["url"], 3)
                    if url["status"]:
                        article["url"] = url["decoded_url"]
                    else:
                        raise Exception("could not decode article url")
                except Exception as e:
                    print(f"Error decoding URL of {article}")
                    continue

                try:
                    news_article = newspaper.article(article["url"], language='de')
                    news_article.download()
                    news_article.parse()
                except Exception as e:
                    print(f"Error parsing news article: {e}")
                    continue

                if not news_article.is_valid_body():
                    print("invalid article body")
                    continue

                full_text = news_article.text
                generate_article_summary_message = [
                    {
                        "content": "Du erhältst vom Nutzer den amtlichen Titel eines deutschen Gesetzes und einen Nachrichtenartikel. Falls der Nachrichtenartikel nichts mit dem Gesetz zu tun hat, antworte ausschließlich mit dem Wort False. Andernfalls, antworte ausschließlich mit einer Zusammenfassung der wichtigsten Aussagen des Nachrichtenartikels, die maximal 1500 Zeichen lang sein darf.",
                        "role": "system"
                    },
                    {
                        "content": f"Amtlicher Gesetzestitel:{law.titel}\nNachrichtenartikel:{full_text}",
                        "role": "user"
                    }
                ]
                try:
                    ai_response = client.chat.completions.create(model=AI_GENERAL_PURPOSE_MODEL, messages=generate_article_summary_message, temperature=0.7, stream=False)
                    summary = ai_response.choices[0].message.content
                except Exception as e:
                    print(f"Error generating article summary: {e}")
                    continue

                if summary == "False":
                    false_hits += 1
                    continue

                article["summary"] = summary
                articles.append(article)
        
        if len(articles) > MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY:
            stripped_down_articles = json.dumps([{"Überschrift": article["title"], "Zusammenfassung": article["summary"], "Quelle": article["publisher"]} for article in articles], ensure_ascii=False)
            summary_message = f"Die folgenden Nachrichtenartikel sind innerhalb eines bestimmten Zeitraums während des Gesetzgebungsverfahrens erschienen. Am Anfang dieses Zeitraums steht folgendes Ereignis: {infos[i]['text'][:infos[i]['text'].find('.')]}."
            summary_message += "Dieses Ereignis markiert zugleich den bislang letzten Schritt im Gesetzgebungsverfahren. Der Zeitraum, aus dem die folgenden Nachrichtenartikel stammen, reicht somit bis zum heutigen Tag.\n\n" if i == len(infos) - 1 or infos[i + 1].get("datum", None) is None else f" Am Ende dieses Zeitraums steht folgendes Ereignis: {infos[i+1]['text'][:infos[i+1]['text'].find('.')]}.\n\n"
            generate_overall_summary_message = [
                {
                    "content": f"Du erhältst vom Nutzer eine Liste strukturierter Daten. Die Liste besteht aus Nachrichtenartikeln über ein deutsches Gesetz mit dem amtlichen Titel {law.titel}, wobei für jeden Artikel die Felder Überschrift, Zusammenfassung und Quelle angegeben sind. Alle Nachrichtenartikel in der Liste sind innerhalb eines bestimmten Zeitraums während des Gesetzgebungsverfahrens erschienen, z.B. nach der 1. und vor der 2. Lesung im Bundestag. Der Nutzer wird dir mitteilen, aus welchem Zeitraum die Artikel stammen. Identifiziere anhand der Titel und Zusammenfassungen die wesentlichen Themen der Nachrichtenartikel, und erstelle dann auf maximal {MAX_OVERALL_SUMMARY_LENGTH} Zeichen eine Zusammenfassung der Berichterstattung über das Gesetz während dieses Zeitraums. Interessante Aspekte, die du in die Zusammenfassung aufnehmen solltest, sind zum Beispiel: Lob und Kritik zu dem Gesetz, die politische und mediale Auseinandersetzung mit dem Gesetz, Besonderheiten des Gesetzgebungsverfahrens, Klagen gegen das Gesetz, Stellungnahmen von durch das Gesetz betroffenen Personen sowie einzelne, besonders im Fokus stehende Passagen des Gesetzes. Weniger interessant ist hingegen eine neutrale Schilderung der wesentlichen Inhalte des Gesetzes - diese solltest du in deine Zusammenfassung nur aufnehmen, wenn sich aus den Artikeln nichts anderes interessantes ergibt.",
                    "role": "system"
                },
                {
                    "content": summary_message + stripped_down_articles,
                    "role": "user"
                }
            ]
            try:
                response = client.chat.completions.create(model=AI_GENERAL_PURPOSE_MODEL, messages=generate_overall_summary_message, temperature=0.7, stream=False)
                summary = response.choices[0].message.content
            except Exception as e:
                print(f"Error generating final summary: {e}")

            info = {"datum": start_date.strftime("%d. %B %Y"), 
                    "vorgangsposition": "Nachrichtenartikel",
                    "text": summary}
            infos = infos[:i+1] + [info] + infos[i+1:]
            i += 1

            # candidates["articles"].append({"Indexnummer": len(articles) -1, "titel": article["title"], "description": article["description"], "url": article["url"]})
    
        # try:
        #     message = client.beta.threads.messages.create(thread_id=thread.id, role="user", content=f"BESTES ERGEBNIS AUSWÄHLEN:\n{json.dumps(candidates)}")
        #     run = client.beta.threads.runs.create_and_poll(thread_id=thread.id, assistant_id=assistant.id)

        #     if run.status == "completed":
                
        #         messages = client.beta.threads.messages.list(thread_id=thread.id)
        #         best_match = int(messages.data[0].content[0].text.value)
                
        #         for message in messages.data:
        #             client.beta.threads.messages.delete(message_id=message.id, thread_id=thread.id)
        
        # except Exception as e:
        #     print(e)

        i += 1
            
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
                info["vorgangsposition"] = "Gesetzentwurf im Bundestag" if position.zuordnung == "BT" else "Gesetzentwurf im Bundesrat"

            case "1. Beratung" | "Zurückverweisung an die Ausschüsse in 2./3. Beratung":
                ausschuesse = sorted(
                    [ueberweisung.ausschuss + " (federführend)" if ueberweisung.federfuehrung \
                     else ueberweisung.ausschuss for ueberweisung in position.ueberweisungen],
                     key=lambda x: " (federführend)" not in x)
                
                ausschuesse = parse_actors(ausschuesse, praepositionen_akkusativ, iterable=True)
                text = "Die 1. Lesung im Bundestag findet statt. Das Gesetz wird überwiesen an\n\n<ul>" if position.vorgangsposition == "1. Beratung" \
                else "Das Gesetz wird in der 2./3. Lesung zurückverwiesen an\n\n<ul>"
                for ausschuss in ausschuesse:
                    text += f"<li>{ausschuss}</li>"
                text += "</ul>"

                # if Zurückverweisung, reset passed Flag on previous Beschlussempfehlung
                if position.vorgangsposition == "Zurückverweisung an die Ausschüsse in 2./3. Beratung":
                    for inf in infos:
                        if inf["vorgangsposition"] in ["Beschlussempfehlung und Bericht", "Beschlussempfehlung"]:
                            inf["passed"] = False

            case "Beschlussempfehlung und Bericht" | "Beschlussempfehlung":
                text = parse_actors(position.urheber_titel, praepositionen_genitiv)
                abstract = position.abstract[12:] if position.abstract.startswith("Empfehlung: ") else position.abstract
                text = "Die Empfehlung " + text + f" lautet: \n<strong>{abstract}</strong>."

            case "Bericht":
                text = parse_actors(position.urheber_titel, praepositionen_genitiv)
                text = "Der Bericht " + text + " liegt vor."

            case "2. Beratung" | "2. Beratung und Schlussabstimmung":                
                if (beschluesse_dritte_beratung := db.session.query(Beschlussfassung).filter(
                    Beschlussfassung.positions_id == Vorgangsposition.id, Vorgangsposition.vorgangs_id == law.id, 
                    Vorgangsposition.vorgangsposition == "3. Beratung", Vorgangsposition.nachtrag == False, Vorgangsposition.datum == position.datum).all()):

                    # some modifications to info because we are merging two vorgangspositionen into one
                    info["vorgangsposition"] = "2. und 3. Beratung"
                    for nachtrag in nachtraege:
                        if nachtrag["vorgangsposition"] == "3. Beratung":
                            info["link"] += f', <a href="{nachtrag["pdf_url"]}">Nachtrag</a>'
    
                    text = "Die 2. und 3. Lesung im Bundestag finden am selben Tag statt."

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
                    text = "Die 2. Lesung im Bundestag findet statt." if position.vorgangsposition == "2. Beratung" else \
                    "Die 2. Lesung und Schlussabstimmung im Bundestag findet statt."
                    text += " Der Beschluss des Bundestags lautet: \n\n" if len(beschluesse) == 1 else \
                    " Die Beschlüsse des Bundestags lauten: \n\n"
                    text += parse_beschluesse(law, beschluesse)
                
                for beschluss in position.beschluesse:
                    if beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit":
                        info["passed"] = False
                    if beschluss.beschlusstenor in ["Ablehnung der Vorlage", "Ablehnung der Vorlagen"]: 
                        info["marks_failure"] = True


            case "3. Beratung":
                daten_zweite_beratung = db.session.execute(db.select(Vorgangsposition.datum).filter(Vorgangsposition.vorgangs_id == law.id, Vorgangsposition.nachtrag == False,
                                        or_(Vorgangsposition.vorgangsposition == "2. Beratung", Vorgangsposition.vorgangsposition == "2. Beratung und Schlussabstimmung"))).scalars().all()
                
                if any(datum == position.datum for datum in daten_zweite_beratung):
                    continue
                
                beschluesse = merge_beschluesse(position.beschluesse)
                text = "Die 3. Lesung im Bundestag findet statt."
                text += " Der Beschluss des Bundestags lautet: \n\n" if len(beschluesse) == 1 else " Die Beschlüsse des Bundestags lauten: \n\n"
                text += parse_beschluesse(law, beschluesse)

                for beschluss in position.beschluesse:
                    if beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit":
                        info["passed"] = False
                    if beschluss.beschlusstenor in ["Ablehnung der Vorlage", "Ablehnung der Vorlagen"]: 
                        info["marks_failure"] = True

            case "1. Durchgang": 
                text = "Der 1. Durchgang im Bundesrat findet statt."
                beschluesse = merge_beschluesse(position.beschluesse)
                text += " Der Beschluss des Bundesrats lautet: \n\n" if len(beschluesse) == 1 else " Die Beschlüsse des Bundesrats lauten: \n\n"
                text += parse_beschluesse(law, beschluesse)

                if any(beschluss.beschlusstenor == "Feststellung der Beschlussunfähigkeit" for beschluss in beschluesse):
                    info["passed"] = False

            case "2. Durchgang" | "Durchgang": # Durchgang, wenn initiative = Bundestag, weil es dann keinen 1. Durchgang gab
                text = "Die Beratung und Abstimmung im Bundesrat finden statt."
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

            case "Plenarantrag":
                text = "Im Plenum " + parse_actors(zuordnungen[position.zuordnung], praepositionen_genitiv)
                text += f" wird folgender Antrag gestellt: \n\n<strong>{position.abstract}</strong>."

            case "BR-Sitzung": # kommt bei initiative von Land (typischerweise 2x) oder bei ini von BT/BRg (nach Anrufung d. Vermittlungsausschusses)
                beschluesse = merge_beschluesse(position.beschluesse)
                text = "Der Bundesrat befasst sich mit dem Gesetz und beschließt:\n\n"
                text += parse_beschluesse(law, beschluesse)

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
                text = f"Im {zuordnungen[position.zuordnung]} wird eine Berichtigung (meist eine Korrektur redaktioneller Fehler) beschlossen."

            # case "...BR" included only as a fallback, likely won't match for the BR as gang tends to be False, VA-Anrufung by BR is instead handled in Durchgang.
            case "Unterrichtung über Anrufung des Vermittlungsausschusses durch die BRg" | "Unterrichtung über Anrufung des Vermittlungsausschusses durch den BR":
                info["vorgangsposition"] = "Unterrichtung über Anrufung des Vermittlungsausschusses durch die Bundesregierung" if position.vorgangsposition.endswith("BRg") \
                else "Unterrichtung über Anrufung des Vermittlungsausschusses durch den Bundesrat" 
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" unterrichtet den {zuordnungen[position.zuordnung]} darüber, dass sie den Vermittlungsausschuss angerufen hat."
                va_angerufen = True

            case "Unterrichtung über Stellungnahme des BR und Gegenäußerung der BRg":
                info["vorgangsposition"] = "Unterrichtung über Stellungnahme des Bundesrats und Gegenäußerung der Bundesregierung"
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" unterrichtet den {zuordnungen[position.zuordnung]} über die Stellungnahme des Bundesrats und die Gegenäußerung der Bundesregierung."

            case "Unterrichtung über Zustimmungsversagung durch den BR":
                info["vorgangsposition"] = "Unterrichtung über Zustimmungsversagung durch den Bundesrat."
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" unterrichtet den {zuordnungen[position.zuordnung]} über die Zustimmungsversagung des Bundesrats."

            case "Vermittlungsvorschlag" | "Einigungsvorschlag":
                text = parse_actors(position.urheber_titel, praepositionen_nominativ, capitalize=True)
                text += f" legt dem {zuordnungen[position.zuordnung]} den {position.vorgangsposition} des Vermittlungsausschusses vor."
                abstract = position.abstract[12:] if position.abstract.startswith("Empfehlung: ") else position.abstract
                text += f" Seine Empfehlung lautet: \n<strong>{abstract}</strong>"

                if position.vorgangsposition == "Vermittlungsvorschlag":
                    pfad.append(copy.deepcopy(abstimmung_ueber_vermittlungsvorschlag_im_bt))

            case "Abstimmung über Vermittlungsvorschlag":
                text = f"Im {zuordnungen[position.zuordnung]} wird über den Vermittlungsvorschlag abgestimmt. Das Abstimmungsergebnis lautet: \n\n"
                beschluesse = merge_beschluesse(position.beschluesse)
                text += parse_beschluesse(law, beschluesse)

                if not any(beschluss.beschlusstenor == "Annahme" for beschluss in beschluesse): # possibly refine with more examples?
                    info["passed"] = False
                    text += "\n\n Damit ist das Gesetz gescheitert. Das Gesetzgebungsverfahren ist am Ende."
                    info["marks_failure"] = True

            case "Protokollerklärung/Begleiterklärung zum Vermittlungsverfahren":
                abstract = position.abstract if position.abstract else ""
                text = f"Im {zuordnungen[position.zuordnung]} wird eine Erklärung zum Vermittlungsverfahren abgegeben: {abstract}."

            case "Rücknahme der Vorlage" | "Rücknahme des Antrags":
                typ = "die Vorlage" if position.vorgangsposition == "Rücknahme der Vorlage" else "der Antrag"
                text = f"Im {zuordnungen[position.zuordnung]} wird {typ} zurückgenommen. Damit ist das Gesetzgebungsverfahren beendet."
                info["marks_failure"] = True

            case "Unterrichtung":
                text = f"Im {zuordnungen[position.zuordnung]} findet folgende Unterrichtung statt: \n{position.abstract}."

        info["text"] = text
        infos.append(info)


    # -------------------- Phase 2: Check how far we have come ------------------- #
    # ------------------- add what remains to be done to infos ------------------- #

    # No need to process remaing if law has already failed or succeeded
    for info in infos:
        if info["marks_failure"]:
            return render_template("results.html", titel=law.titel, beratungsstand=beratungsstand, abstract=law_abstract, zustimmungsbeduerftigkeit=zustimmungsbeduerftigkeit, infos=infos)
        if info["marks_success"]:
            if beratungsstand == "Nicht ausgefertigt wegen Zustimmungsverweigerung des Bundespräsidenten":
                info["text"] += "\n\n<strong>Der Bundespräsident hat sich jedoch wegen verfassungsrechtlicher Bedenken geweigert, das Gesetz auszufertigen. Es wird somit nicht in Kraft treten</strong>."
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
