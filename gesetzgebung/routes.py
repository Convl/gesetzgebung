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
from openai import OpenAI

THE_NEWS_API_KEY = 'lglEeSs4tfC3vW2IgkThxlmBrEk4e8YjZg1MnopQ'
THE_NEWS_API_TOP_STORIES_ENDPOINT = 'https://api.thenewsapi.com/v1/news/top'
THE_NEWS_API_ENDPOINT = 'https://api.thenewsapi.com/v1/news/all'

@app.route("/bla")
def bla():
    # BING_API_KEY = os.environ.get("BING_API_KEY")
    # BING_NEWS_API_ENDPOINT = "https://api.bing.microsoft.com/v7.0/news/search"
    # BING_SEARCH_API_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
    # headers = {'Ocp-Apim-Subscription-Key': BING_API_KEY} # TODO: pass User-Agent
    # query = "Selbstbestimmungsgesetz"
    # params = {'q': query, 
    #           'mkt': 'de-DE', 
    #           'textDecorations': True, 
    #           'textFormat': 'HTML',
    #           'responseFilter': 'News',
    #           'count': '100',
    #           }
    # response = requests.get(BING_NEWS_API_ENDPOINT, headers=headers, params=params)
    # return response.json()
    
    THE_NEWS_API_KEY = os.environ.get("THE_NEWS_API_KEY")
    THE_NEWS_API_TOP_STORIES_ENDPOINT = 'https://api.thenewsapi.com/v1/news/top'
    THE_NEWS_API_ENDPOINT = 'https://api.thenewsapi.com/v1/news/all'

    laws = get_all_laws()

    # "Europäischen", "(EU)" -> "EU*"
    # *gesetzes, *buches, Schutzes, Abkommens, Rechts, *plans, 
    # endswith "rechtlicher"/"rechtlichen"/"rechtliche" -> der Teil davor als (Teildavor* | teildavor*), ggf noch das 's' weg (versicherungSrechtlicher, auslandSrechtlicher, aber: soldatenrechtlicher)
    eu_synonyms = {"(EU)": "(EU* | Europäische* Union)",
                    "Europäische": "(EU* | Europäische* Union)",
                    "Union": "(EU* | Europäische* Union)",
                    "Parlament": "(EU* | Europäische* Union)",
                    "Bundeshaushaltsplan": "(Bundeshaushaltsplan* | Bundeshaushalt* | Haushalt*)",
                    }
    add = {"Gesetz*"} # unless Richtlinie / Verordnung / Übereinkommen / Abkommen (all potentially with -s)
    keep = {"Richtlinie", "Anpassung", "Modernisierung", "Verbesserung", "Stärkung", "Beschleunigung", "Schutz", "Aufhebung", "Verordnung", "Bekämpfung", "2023", "2024", "Förderung", 
    "Digitalisierung", "Übereinkommen", "Transparenz", "Doppelbesteuerung", "Erhöhung", "Sicherung", "Verhinderung", "Entlastung", "Verlängerung", "Ausbau", "Durchsetzung",
    "Kindern", "Finanzierung", "Gewalt", "Unternehmen", "Wohnraum", "Übereinkommen", "Steigerung", "Erleichterung", "Verfahren", "Unterbringung", "Nutzung", "Stiftung", "Verfolgung",
    "Bundestag", "Begrenzung", } # Errichtung? Einkommen, Vermögen, Zusammenarbeit wenn nicht "Doppelbesteuerung"? Personen?
    synonyms = {"Strafgesetzbuch*": "(Strafgesetzbuch* | StGB)",
                "Sozialgesetzbuch*": "(Sozialgesetzbuch* | SGB)",
                "Strafprozessordnung*": "(Strafprozessordnung | StPO)",
                "EU*": "(EU* | Europäische* Union)",
                "Union*": "(EU* | Europäische* Union)",
                "Rat*": "(EU* | Europäische* Rat*)",
                }
    # delete = {"Gesetz", "Änderung", "Vorschriften", "Einführung", "Gesetzes", "Umsetzung", "Gesetze", "Europäischen", "(EU)", "Deutschland", "Bundesrepublik",
    #  "Rates", "Regierung", "Republik", "Regelungen", "§", "Buches", "Vermeidung", "Regelung", 
    #  "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember", 
    #  "Erstes", "Zweites", "Drittes", "Viertes", "Fünftes", "Sechstes", "Siebtes", "Achtes", "Neuntes", "Zehntes", "Elftes", "Zwölftes", "Dreizehntes",
    #  "Vierzehntes", "Fünfzehntes", "Sechszehntes", "Siebzehntes", "Achtzehntes", "Neunzehntes", "Zwangzigstes", "Einunzwandzigstes", "Zweiundzwanzigstes", 
    #  "Dreiundzwanzigstes", "Vierundzwanzigstes", "Fünfundzwanzigstes", "Sechsundzwanzigstes", "Siebenundzwanzigstes", "Achtundzwanzigstes", "Neunundzwanzigstes", "Dreißigstes", 
    #  "Protokoll", "Errichtung", "Änderungen", "Steuern", "Gebiet", "Maßnahmen", "Einkommen", "Neuregelung", "Deutschen", "Personen", "Haushaltsjahr", "Mitgliedstaaten", 
    #  "Bereich", "Vermögen", "Zusammenhang", "Zusammenarbeit", "Jahr", "Rahmenbedingungen", "Weiterentwicklung", "Sicherstellung", "Bestimmungen", "Ausgestaltung", "Artikel", } # Anpassung? Modernisierung? Verbesserung? Stärkung? Jahreszahlen? sonstige Zahlen wie 29.?

    ignore = {"Änderung", "Vorschrift", "Einführung", "Umsetzung", "Deutschland", "Bundesrepublik",
     "Rat", "Regierung", "Republik", "Regelung", "§", "Buch", "Vermeidung", "Regelung", 
     "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember", 
     "Protokoll", "Errichtung", "Steuer", "Gebiet", "Maßnahme", "Einkommen", "Neuregelung", "Person", "Haushaltsjahr", "Mitgliedstaat", 
     "Bereich", "Vermögen", "Zusammenhang", "Zusammenarbeit", "Jahr", "Rahmenbedingung", "Weiterentwicklung", "Sicherstellung", "Bestimmung", "Ausgestaltung", "Artikel", 
     "Bezug", } # Anpassung? Modernisierung? Verbesserung? Stärkung? Jahreszahlen? sonstige Zahlen wie 29.?

    results = {"winner by hits": {"abbreviated": 0, "manual": 0, "chatgpt": 0},
               "winner by relevance": {"abbreviated": 0, "manual": 0, "chatgpt": 0}, 
               "queries": [],
               "had abbreviation": 0}
    nlp = spacy.load("de_core_news_sm") # or de_dep_news_trf
    client = OpenAI()
    assistant = client.beta.assistants.retrieve("asst_71hSSTXEzsh5NrZoPcIrxpZw")
    thread = client.beta.threads.create()
    counter = 0

    for law in laws:
        if counter > 250:
            break
        counter += 1

        titel : str = law.titel
        word = ""
        words = []
        queries = {}

        daten = [position.datum for position in law.vorgangspositionen if position.gang]
        daten.sort()
        start_date = daten[0].strftime("%Y-%m-%d")
        end_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # generate query from shorthand if there is one
        if titel[-1] == ")":
            abbreviation_start = parentheses_start = max(6, titel.rfind("(")) # There will never be a ( before index 6, max is just in case there is a ) without a ( in the title
            abbreviation_start = parentheses_start + 1
            while titel[abbreviation_start].isdigit() or titel[abbreviation_start] in {".", " "}: # (2. Betriebsrentenstärkungsgesetz) -> Betriebsrentenstärkungsgesetz
                abbreviation_start += 1
            abbreviation_start = max(abbreviation_start, titel.find("- und ", abbreviation_start, len(titel) - 1) + 6) # (NIS-2-Umsetzungs- und Cybersicherheitsstärkungsgesetz) -> Cybersicherheitsstärkungsgesetz
            abbreviation_end = titel.find(" - ", abbreviation_start, len(titel) - 1) if titel.find(" - ", abbreviation_start, len(titel) - 1) > 0 else len(titel) - 1
            queries["abbreviated"] = {"search query": titel[abbreviation_start:abbreviation_end]}
            titel = titel[:parentheses_start - 1] # remove parentheses after processing them
            results["had abbreviation"] += 1
        
        # generate query manually with spaCy
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
        
        queries["manual"] = {"search query": " ".join(word for word in words)}

        # generate query with ChatGPT
        system_prompt = """Du bist ein hilfreicher Assistent, dem ich die amtlichen Titel deutscher Gesetze schicken werde. 
        Diese amtlichen Titel sind oft sehr lang und klingen nach Behördensprache. 
        In Nachrichtenartikeln über das Gesetz wird deshalb häufig nicht der volle amtliche Titel verwendet, sondern eine kürzere Bezeichnung, die sich aus dem amtlichen Titel ableitet. 
        Ich möchte mit einer Suchmaschine nach Nachrichtenartikeln über das Gesetz suchen. 
        Dazu brauche ich einen guten Suchbegriff, der möglichst viele relevante Resultate liefert. 
        Ich möchte von dir, dass du dir zuerst überlegst, mit welchem Begriff / welchen Begriffen das Gesetz vermutlich in Nachrichtenartikeln bezeichnet wird. 
        Dann möchte ich, dass du eine Suchanfrage für eine Suchmaschine konstruierst, die möglichst viele solcher Nachrichtenartikel findet, und mir ausschließlich mit einer solchen Suchanfrage antwortest. 
        Du kannst folgende Operatoren nutzen, um die Suchanfrage zu konstruieren:
        | (ODER) 
        + (UND) 
        - (NICHT) 
        "" (EXAKTE WORTGRUPPE) 
        * (WILDCARD, nur am Ende eines Wortes zwecks Prefixsuche zulässig) 
        () (PRÄZEDENZ, um zu definieren, auf welche Begriffe sich andere logische Operatoren beziehen)
        Du solltest grundsätzlich an jedes Wort ein * anhängen.
        Ein Beispiel für eine Suchanfrage zu einem Gesetz mit dem Titel "Gesetz über die Selbstbestimmung in Bezug auf den Geschlechtseintrag und zur Änderung weiterer Vorschriften" wäre: Selbstbestimmungsgesetz* | (Gesetz* + Selbstbestimmung* + Geschlechtseintrag*)"""
        message = client.beta.threads.messages.create(thread_id=thread.id, role="user", content=titel)
        run = client.beta.threads.runs.create_and_poll(thread_id=thread.id, assistant_id=assistant.id)
        assistant = assistant or client.beta.assistants.create(name="Suchanfrage_aus_Gesetzestitel", instructions=system_prompt, model="gpt-4o")
        
        try:
            if run.status == "completed":
                messages = client.beta.threads.messages.list(thread_id=thread.id)
                queries["chatgpt"] = {"search query": messages.data[0].content[0].text.value}
                
                for message in messages.data:
                    client.beta.threads.messages.delete(message_id=message.id, thread_id=thread.id)
        except Exception as e:
            print(e)

        # run news search on all queries
        params = {'api_token': THE_NEWS_API_KEY,
        'search': "",
        'language': 'de',
        'published_after': start_date,
        'published_before': end_date,
        'page': 1
        }
        
        for method in queries:
            params["search"] = queries[method]["search query"]
            response = requests.get(THE_NEWS_API_ENDPOINT, params=params)
            hits = response.json()["meta"]["found"]
            queries[method]["hits"] = hits
            if hits > 0:
                queries[method]["title"] = response.json()["data"][0]["title"]
                queries[method]["description"] = response.json()["data"][0]["description"]
                queries[method]["url"] = response.json()["data"][0]["url"]
                queries[method]["relevance"] = response.json()["data"][0]["relevance_score"]
        
        try:
            winner_by_hits = max(queries, key=lambda method: queries[method].get("hits", 0))
            winner_by_relevance = max(queries, key=lambda method: queries[method].get("relevance", 0))
            results["winner by hits"][winner_by_hits] += 1
            results["winner by relevance"][winner_by_relevance] += 1
            results["queries"].append({"Titel": titel, "Querries": queries})
        except Exception as e:
            print(e)
        #print(f"Titel: {law.titel}\nAbbreviated: {queries['abbreviated']}\nManual: {queries['manual']}\nChatGPT: {queries['chatgpt']}\n\n")

        # search_terms = [token.lemma_ for token in doc if token.pos_ in {"NOUN", "PROPN"}]
        # print(f"Law.titel: {law.titel}\nSearch terms: {search_terms}")
    return results

        # if "Gesetz " not in law.titel:
        #     end = law.titel.find("gesetz") + 6
        #     start = max(0, law.titel.find(" ", 0, end))
        #     query = law.titel[:law.titel.find("gesetz") + 6]
        # else:
        #     words : str = law.titel.split()
        #     for word in words:
        #         if word[0].islower() or word in ignore:
        #             continue

        #         all_words[word] = all_words.get(word, 0) + 1

    all_words = dict(sorted(all_words.items(), key = lambda item:item[1], reverse=True))
    all_words_list = []

    for word in all_words:
        all_words_list.append({word: all_words[word]})
        # print(f"Word: {word}, count: {all_words[word]}")

    return all_words_list


    for law in laws:
        if i > 50:
            break

        daten = [position.datum for position in law.vorgangspositionen]
        daten.sort()
        start_date = daten[0].strftime("%Y-%m-%d")
        end_date = daten[-1].strftime("%Y-%m-%d")
    
        query = law.titel.replace(" ", " + ")
        params = {'api_token': THE_NEWS_API_KEY,
                'search': query,
                'language': 'de',
                'published_after': start_date,
                'published_before': end_date,
                'page': 1
                }
        response = requests.get(THE_NEWS_API_ENDPOINT, params=params)
        full_title_hits = response.json()["meta"]["found"]

        words : str = law.titel.split()
        query = " ".join(word.replace("(", "").replace(")", "") for word in words if word[0].isupper())
        params["search"] = query
        response = requests.get(THE_NEWS_API_ENDPOINT, params=params)
        substantive_title_hits = response.json()["meta"]["found"]

        start = law.titel.find("(")
        end = law.titel.find(")")
        if start != -1 and end != -1:
            bracketed = law.titel[start+1:end].split()
            query = max(bracketed, key=len)
            params["search"] = query
            response = requests.get(THE_NEWS_API_ENDPOINT, params=params)
            abbreviation_hits = response.json()["meta"]["found"]
            abbreviation_existed += 1
        else:
            abbreviation_hits = 0
    
        if full_title_hits > substantive_title_hits and full_title_hits > abbreviation_hits:
            full_title_best += 1
        elif substantive_title_hits > full_title_hits and substantive_title_hits > abbreviation_hits:
            substantive_title_best += 1
        elif abbreviation_hits > full_title_hits and abbreviation_hits > substantive_title_hits:
            abbreviation_best += 1

        i += 1
        print(f"Law: {law.titel}\nFull title hits: {full_title_hits}\nSubstantive hits: {substantive_title_hits}\nAbbreviation hits: {abbreviation_hits}")
    
    print(f"Full title best: {full_title_best}\nSubstantive best: {substantive_title_best}\nAbbreviation best: {abbreviation_best} / {abbreviation_existed}")

    return response.json()

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

        # query = 'Selbstbestimmungsgesetz'
        # params = {'api_token': THE_NEWS_API_KEY,
        #       'search': query,
        #       'language': 'de',
        #       'published_after': '2024-01-01',
        #       'published_before': '2025-01-01',
        #       'page': 1
        #       }
        # response = requests.get(THE_NEWS_API_ENDPOINT, params=params)



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
