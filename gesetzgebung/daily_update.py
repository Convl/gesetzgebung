import requests
from dotenv import load_dotenv
import datetime
import time
import os
from gesetzgebung.models import *
from gesetzgebung.flask_file import app
from gesetzgebung.es_file import es, ES_LAWS_INDEX
from gesetzgebung.routes import parse_law
# from elasticsearch.exceptions import NotFoundError
from elasticsearch7.exceptions import NotFoundError

import json
from openai import OpenAI
import newspaper
from gnews import GNews
from googlenewsdecoder import gnewsdecoder
import re
from itertools import groupby
import smtplib
import swiftshadow

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

DIP_API_KEY = "I9FKdCn.hbfefNWCY336dL6x62vfwNKpoN2RZ1gp21"
DIP_ENDPOINT_VORGANGLISTE = "https://search.dip.bundestag.de/api/v1/vorgang"
DIP_ENDPOINT_VORGANG = "https://search.dip.bundestag.de/api/v1/vorgang/"
DIP_ENDPOINT_VORGANGSPOSITIONENLISTE = "https://search.dip.bundestag.de/api/v1/vorgangsposition"
DIP_ENDPOINT_VORGANGSPOSITION = "https://search.dip.bundestag.de/api/v1/vorgangsposition/"
FIRST_DATE_TO_CHECK = "2021-10-26"
LAST_DATE_TO_CHECK = datetime.datetime.now().strftime("%Y-%m-%d")

SUMMARY_LENGTH = 700
IDEAL_ARTICLE_COUNT = 5
MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY = 2
MINIMUM_ARTICLE_LENGTH = 3500
MAXIMUM_ARTICLE_LENGTH = 20000
NEWS_UPDATE_CANDIDATES_ROLLBACK_COUNT = 20
AI_API_KEY = os.environ.get("OPENROUTER_API_KEY")
AI_ENDPOINT = "https://openrouter.ai/api/v1"
NEWS_UPDATE_INTERVALS = [datetime.timedelta(days=1), datetime.timedelta(days=3), datetime.timedelta(days=30), datetime.timedelta(days=90), datetime.timedelta(days=180)] + [datetime.timedelta(days=180) * i for i in range(20)]
QUERY_UPDATE_INTERVALS = [datetime.timedelta(days=1), datetime.timedelta(days=30), datetime.timedelta(days=180), datetime.timedelta(days=360)]
headers = {"Authorization": "ApiKey " + DIP_API_KEY}
no_news_found = 0


def daily_update(): 
    with app.app_context():
        # just in case daily update is launched while previous one is still active
        if is_update_active():
            report_error("Daily update launched while still in progress.", f"Immediately terminating new process at {datetime.datetime.now()}.", True)
        set_update_active(True)
        
        # ----------- Phase I: Enter new information from DIP into database ---------- #
        params =    {"f.vorgangstyp": "Gesetzgebung",
                     "f.datum.start": FIRST_DATE_TO_CHECK,
                     "f.aktualisiert.start": last_update
                    } \
                        if (last_update := get_last_update()) else \
                    {"f.vorgangstyp": "Gesetzgebung", 
                    "f.datum.start": FIRST_DATE_TO_CHECK, 
                    "f.datum.end": LAST_DATE_TO_CHECK
                    }

        cursor = ""
        
        response = requests.get(DIP_ENDPOINT_VORGANGLISTE, params=params, headers=headers)        
        print("Starting daily update")
        
        while response.ok and cursor != response.json().get("cursor", None):
            response_data = response.json()
            for item in response_data.get("documents", []):
                law = get_law_by_dip_id(item.get("id", None)) or GesetzesVorhaben() 
                print(f"Processing Item id: {item.get("id", None)}, item id type: {type(item.get("id", None))}, law dip id: {law.dip_id}, law dip id type: {type(law.dip_id)}")

                #if not law.aktualisiert or law.aktualisiert != item.get("aktualisiert", None):
                law.dip_id = item.get("id", None)
                law.abstract = item.get("abstract", None)
                if not law.beratungsstand or law.beratungsstand[-1] != item.get("beratungsstand", None):
                    law.beratungsstand.append(item.get("beratungsstand", None))
                law.sachgebiet = [sg for sg in item.get("sachgebiet", [])]
                law.wahlperiode = int(item.get("wahlperiode", None))
                law.zustimmungsbeduerftigkeit = [zb for zb in item.get("zustimmungsbeduerftigkeit", [])]
                law.initiative  = [ini for ini in item.get("initiative", [])]
                law.aktualisiert = item.get("aktualisiert", None)
                law.titel = item.get("titel", None)
                law.datum = item.get("datum", None)
                

                update_positionen(item.get("id", None), law)

                db.session.add(law)
                db.session.commit()
                
                if item.get("verkuendung", []):
                    update_verkuendung(item.get("verkuendung", []), law)

                if item.get("inkrafttreten", []):
                    update_inkrafttreten(item.get("inkrafttreten", []), law)

                db.session.commit()
                
                update_law_in_es(law)
                
                print(f"Entered into database: law dip id: {law.dip_id}, law dip id type: {type(law.dip_id)}, law id: {law.id}")

                time.sleep(1)
            
            print(f"old cursor: {cursor}")
            params["cursor"] = cursor = response.json().get("cursor", None)
            print(f"new cursor: {cursor}")
            response = requests.get(DIP_ENDPOINT_VORGANGLISTE, params=params, headers=headers)
            print(f"next cursor: {response.json().get("cursor", None)}")

        set_last_update(datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

        # --------- Phase 2: Update news articles / summaries where necessary -------- #
        """Process for updating news articles / creating summaries:
        - Check all NewsUpdateCandidates (i.e. Vorgangspositionen that haven't had a news summary added in a while, or at all)
        - If a NewsUpdateCandidate is new, it receives its first update, any older NewsUpdateCandidates belonging to the same law receive their final update and are removed from the list
        - If no new NewsUpdateCandidates were added for a given law, existing ones get updated periodically in increasing intervals
        - Updating means that news articles for the relevant timeframe will be searched, and a summary will (usually) be created.
        """
        
        client = OpenAI(base_url=AI_ENDPOINT, api_key=AI_API_KEY)
        gn = GNews(language='de', country='DE')
        now = datetime.datetime.now().date()
        
        all_candidates = (db.session.query(NewsUpdateCandidate)
        .join(Vorgangsposition)  
        .join(GesetzesVorhaben)  
        .order_by(
            GesetzesVorhaben.id,  
            Vorgangsposition.datum  
        )
        .all())
        candidate_groups = {law_id: sorted(list(group), key=lambda c: c.position.datum, reverse=True)
                            for law_id, group in groupby(all_candidates, key=lambda c: c.position.gesetz.id)}
        
        saved_for_rollback = []
        for law_id, candidates in candidate_groups.items():
            print(f"*** Starting news update for law with id {law_id}, update candidate ids: {[c.id for c in candidates]} ***")
            newer_exists = False
            law = get_law_by_id(law_id)
            infos = parse_law(law, display=False)
            
            completion_state = ""
            for info in infos:
                if info["marks_success"]:
                    completion_state = "Das Ereignis, das den Start dieses Zeitraums markiert, markiert zugleich den erfolgreichen Abschluss des Gesetzgebungsverfahrens."
                elif info["marks_failure"]:
                    completion_state = "Das Ereignis, das den Start dieses Zeitraums markiert, markiert zugleich das Scheitern des Gesetzgebungsverfahrens."
            completion_state = completion_state or "Das Ereignis, das den Start dieses Zeitraums markiert, ist das momentan aktuellste im laufenden Gesetzgebungsverfahren."
            dummy_info = {"datetime": now, "ai_info": f"{completion_state} Die mit diesem Zeitraum verknüpften Nachrichtenartikel reichen somit bis zum heutigen Tag."}   
                       
            for i, candidate in enumerate(candidates):
                position = candidate.position
                info = next(inf for inf in infos if inf["id"] == position.id) # add a default here in case no match is found? That shouldn't be possible though
                next_info = next(inf for inf in infos if inf["id"] == candidates[i-1].position.id) if i > 0 else dummy_info

                # not due for its final update (newer_exists=False), has already been updated (next_update=True), not due for next update(next_update>now) -> skip
                if not newer_exists and candidate.next_update and candidate.next_update > now:
                    continue

                update_queries(client, law, now)
                if not law.queries:
                    print(f"CRITICAL: No search queries available for law with id {law.id}, skipping.")
                    continue
                
                if len(saved_for_rollback) >= NEWS_UPDATE_CANDIDATES_ROLLBACK_COUNT:
                    saved_for_rollback.pop(0)
                saved_for_rollback.append(SavedNewsUpdateCandidate(candidate))

                update_news(client, gn, position, [info] + [next_info], law.queries, saved_for_rollback, law)

                if newer_exists:
                    db.session.delete(candidate)
                elif not candidate.next_update or candidate.next_update <= now:
                    if not candidate.next_update:
                        newer_exists = True  
                    candidate.last_update = now
                    # simpler version to replace 3 lines below, but does not handle initial runs with historical data well: candidate.next_update = (now + NEWS_UPDATE_INTERVALS[min(len(NEWS_UPDATE_INTERVALS) - 1, candidate.update_count)])
                    offset = 0
                    while position.datum + NEWS_UPDATE_INTERVALS[offset] < now and offset < len(NEWS_UPDATE_INTERVALS) - 1:
                        offset += 1
                    candidate.next_update = now + NEWS_UPDATE_INTERVALS[offset]
                    candidate.update_count += 1
                db.session.commit()
        
        set_update_active(False)

def update_queries(client, law, now):
    # If queries haven't been updated in a while / at all, update them now
    last_updated = law.queries_last_updated or datetime.date(1900, 1, 1)
    if now - last_updated > QUERY_UPDATE_INTERVALS[min(law.query_update_counter, len(QUERY_UPDATE_INTERVALS) - 1)]:
        law.queries = generate_search_queries(client, law)
        if law.queries: 
            law.queries_last_updated = now
            law.query_update_counter += 1

def update_news(client, gn, position, infos, queries, saved_candidates, law=None):
    news_info = get_news(client, gn, infos, law, queries, position, saved_candidates)
    
    if not news_info["zusammenfassung"]:
        return

    if position.summary:
        for article in position.summary.articles:
            db.session.delete(article)
        db.session.delete(position.summary)
    
    summary = NewsSummary()
    summary.summary = news_info["zusammenfassung"]
    summary.articles_found = news_info["relevant_hits"]
    summary.position = position
    db.session.add(summary) # need to commit here for articles to get added propperly?

    for article in news_info["article_data"]:
        a = NewsArticle()
        a.description = article.get("description", "")
        a.publisher = article.get("publisher", {}).get("title", "")
        a.published_date = article.get("published date", None)
        a.title = article.get("title", "")
        a.url = article.get("url", "")
        a.summary = summary
        db.session.add(a)
    db.session.commit()

def update_inkrafttreten(inkrafttreten, law):
    existing_inkrafttreten = db.session.query(Inkrafttreten).filter_by(vorgangs_id=law.id).all()
    for inkraft in existing_inkrafttreten:
        db.session.delete(inkraft)

    for item in inkrafttreten:
        inkraft = Inkrafttreten()
        inkraft.datum = item.get("datum", None)
        inkraft.erlaeuterung = item.get("erlaeuterung", None)

        inkraft.inkrafttreten_vorhaben = law
        db.session.add(inkraft)

def update_verkuendung(verkuendungen, law):
    existing_verkuendungen = db.session.query(Verkuendung).filter_by(vorgangs_id=law.id).all()
    for verkuendung in existing_verkuendungen:
        db.session.delete(verkuendung)
    
    for item in verkuendungen:
        verkuendung = Verkuendung()
        verkuendung.ausfertigungsdatum = item.get("ausfertigungsdatum", None)
        verkuendung.verkuendungsdatum = item.get("verkuendungsdatum", None)
        verkuendung.pdf_url = item.get("pdf_url", None)
        verkuendung.fundstelle = item.get("fundstelle", None)

        verkuendung.vorhaben = law
        db.session.add(verkuendung) 

def update_positionen(dip_id, law):
    params = {"f.vorgang": dip_id}

    cursor = ""
    response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)
    new_position_dates = []
    while response.ok and cursor != response.json().get("cursor", None):
        for item in response.json().get("documents", []):
            new_position = (position := get_position_by_dip_id(item.get("id", None))) is None and item.get("gang", None) is True
            position = position or Vorgangsposition()
            if not position.aktualisiert or position.aktualisiert != item.get("aktualisiert", None): # may wanna check item.get("gang", False) here
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
                db.session.add(position)
                db.session.commit()

                ueberweisungen = item.get("ueberweisung", [])
                update_ueberweisungen(position, ueberweisungen)

                fundstelle = item.get("fundstelle", [])
                update_fundstelle(position, fundstelle)

                beschlussfassungen = item.get("beschlussfassung", [])
                update_beschluesse(position, beschlussfassungen)

                # if the position has been newly added, and no other new positions have already been added for the same day, add it to the queue of NewsUpdateCandidates 
                if new_position and position.datum not in new_position_dates:
                    new_position_dates.append(position.datum)
                    news_update_candidate = NewsUpdateCandidate()
                    news_update_candidate.position = position
                    news_update_candidate.update_count = 0
                    news_update_candidate.last_update = None
                    news_update_candidate.next_update = None
                    db.session.add(news_update_candidate)
        
        time.sleep(1)
        params["cursor"] = cursor = response.json().get("cursor", None)
        response = requests.get(DIP_ENDPOINT_VORGANGSPOSITIONENLISTE, params=params, headers=headers)

def update_beschluesse(position, beschlussfassungen):
    # position.beschluesse.clear()
    existing_beschluesse = db.session.query(Beschlussfassung).filter_by(positions_id=position.id).all()
    if existing_beschluesse:
        for beschluss in existing_beschluesse:
            db.session.delete(beschluss)

    for item in beschlussfassungen:
        beschluss = Beschlussfassung()
        beschluss.beschlusstenor = item.get("beschlusstenor", None)
        beschluss.dokumentnummer = item.get("dokumentnummer", None)
        beschluss.seite = item.get("seite", None)
        beschluss.abstimm_ergebnis_bemerkung = item.get("abstimm_ergebnis_bemerkung", None)
        
        beschluss.position = position
        db.session.add(beschluss)


def update_fundstelle(position, dip_fundstelle):
    # position.fundstelle.clear()
    existing_fundstellen = db.session.query(Fundstelle).filter_by(positions_id=position.id).all()
    if existing_fundstellen:
        for fundstelle in existing_fundstellen:
            db.session.delete(fundstelle)

    fundstelle = Fundstelle()
    fundstelle.dip_id = dip_fundstelle.get("id", None)
    fundstelle.dokumentnummer = dip_fundstelle.get("dokumentnummer", None)
    fundstelle.drucksachetyp = dip_fundstelle.get("drucksachetyp", None)
    fundstelle.herausgeber = dip_fundstelle.get("herausgeber", None)
    fundstelle.pdf_url = dip_fundstelle.get("pdf_url", None)
    fundstelle.urheber = [urheber for urheber in dip_fundstelle.get("urheber", [])]
    fundstelle.anfangsseite = dip_fundstelle.get("anfangsseite", None)
    fundstelle.endseite = dip_fundstelle.get("endseite", None)
    fundstelle.anfangsquadrant = dip_fundstelle.get("anfangsquadrant", None)
    fundstelle.endquadrant = dip_fundstelle.get("endquadrant", None)

    fundstelle.position = position
    db.session.add(fundstelle)

def update_ueberweisungen(position, ueberweisungen):
    existing_ueberweisungen = db.session.query(Ueberweisung).filter_by(positions_id=position.id).all()
    if existing_ueberweisungen:
        for ueberweisung in existing_ueberweisungen:
            db.session.delete(ueberweisung)

    for item in ueberweisungen:
        ueberweisung = Ueberweisung()
        ueberweisung.ausschuss = item.get("ausschuss", None)
        ueberweisung.ausschuss_kuerzel = item.get("ausschuss_kuerzel", None)
        ueberweisung.federfuehrung = item.get("federfuehrung", None)

        ueberweisung.position = position
        db.session.add(ueberweisung)

def get_news(client, gn, infos, law, queries, position, saved_candidates):
    global no_news_found # prefer this over passing it around between a bunch of functions that mostly don't need it

    start_date = infos[0]["datetime"]
    end_date = infos[1]["datetime"]
    news_info = {"start": infos[0]['ai_info'], "end": infos[1]["ai_info"], "artikel": [], "article_data": [], "relevant_hits": 0, "zusammenfassung": None}

    gn.start_date = (start_date.year, start_date.month, start_date.day)
    gn.end_date = (end_date.year, end_date.month, end_date.day)

    print(f"retrieving news from {news_info['start']} to {news_info['end']}")
    for query in queries:
        time.sleep(1)

        # If no news have been found for a while, check if it is just a coincidence, or if gnews is blocking us.
        # Using NEWS_UPDATE_CANDIDATES_ROLLBACK_COUNT * 3 to be on the safe side, though some laws likely had 4 candidates. 
        if no_news_found >= NEWS_UPDATE_CANDIDATES_ROLLBACK_COUNT * 3:
            consider_rollback(saved_candidates)

        try:
            if not (gnews_response := gn.get_news(query)):
                no_news_found += 1
                raise Exception("did not get a response from gnews")
        except Exception as e:
            print(f"Error fetching news from gnews for query: {query}. Error: {e}. Start date: {gn.start_date}. End date: {gn.end_date}")
            continue
        
        no_news_found = 0
        print(f"found {len(gnews_response)} articles for query: {query}")
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
                    "content": json.dumps([{'index': i, 'titel': article["title"]} for i, article in enumerate(gnews_response)], ensure_ascii=False),
                    "role": "user"
                }
            ]
            ai_response = get_structured_data_from_ai(client, evaluate_results_messages, evaluate_results_schema, "artikel")

            for i in range(len(gnews_response) - 1, -1, -1):
                if ai_response[i]["passend"] in {0, '0'}:
                    gnews_response.pop(i)

        except Exception as e:
            print(f"Error evaluating search results: {e}")
            continue

        # Decided to count the relevant hits for the most succesful query only, as this likely skews the results less than the alternatives. Ultimately,
        # all methods are imperfect, since we are limited to 100 results from gnews. Possibly change this in the future to scrape the total result count
        # from a google news web search directly, provided we have a query that yields no / acceptably few false positives. 
        news_info["relevant_hits"] = max(news_info["relevant_hits"], len(gnews_response))
        print(f"found {len(gnews_response)} relevant titles for query: {query}")

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
                print(f"Unknown Error {e} while decoding URL of {article}")
                continue 
            
            # this check has only been added after law 598, see above
            if any(article["url"] == existing_article["url"] for existing_article in news_info["article_data"]):
                continue

            try:
                news_article = newspaper.article(article["url"], language='de')
                news_article.download()
                news_article.parse()
            except Exception as e:
                print(f"Error parsing news article: {e}")
                continue

            if not news_article.is_valid_body() or len(news_article.text) < MINIMUM_ARTICLE_LENGTH or len(news_article.text) > MAXIMUM_ARTICLE_LENGTH:
                continue
            
            # sometimes articles that got updated later are included in the response from Google News. This filters out some of those, though still not all.
            if not news_article.publish_date or news_article.publish_date.date() >= end_date:
                continue

            news_info["artikel"].append(news_article.text)
            news_info["article_data"].append(article)

    if len(news_info["artikel"]) < MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY:
        print(f"Only found {len(news_info['artikel'])} usable articles, need {MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY} to display summary.")
        return news_info

    # if a summary already exists
    if position.summary:
        # ...no need to make a new one if the old one was based on a sufficient number of articles and we haven't seen at least a 1.5x increase in article count since then
        if news_info["relevant_hits"] > position.summary.articles_found >= IDEAL_ARTICLE_COUNT:
            if news_info["relevant_hits"] < position.summary.articles_found * 1.5:
                print(f"Already had {position.summary.articles_found} articles, only have {news_info['relevant_hits']} now, no update needed.")
                return news_info
        # ...obviously, don't make a new one if we haven't seen an increase in article count at all, either
        elif news_info["relevant_hits"] <= position.summary.articles_found:
            print("Did not find more articles this time than last time, no update needed.")
            return news_info
        # ...or if the actual articles that the summary was based on then, and would be based on now, are identical
        # (that would be unfortunate, though: If the article count has increased substantially, 
        # yet the actual articles chosen for the summary creation are the same as last time, that would suggest that there has been a new development, 
        # which is not reflected in the articles chosen for summary creation. I might change the above code to account for this possibility.
        # For now, though, I trust that Google News orders its results such that new articles containing new developments will be amongst the first
        # to get processed, and therefore end up in the selection of articles for the new summary.)
        if all(any(new_article["url"] == existing_article.url for existing_article in position.summary.articles) for new_article in news_info["article_data"]):
            print("Old and new articles identical, no need to update")
            return news_info    

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
            Deine Antwort muss aus reinem, unformatiertem Text bestehen und AUSSCHLIEßLICH die Zusammenfassung enthalten. Sie darf keine weiteren Informationen enthalten, nicht einmal eine einleitende Überschrift wie zum Beispiel "Zusammenfassung:". 
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
        return news_info
    
    news_info["zusammenfassung"] = ai_response
    print(f"generated summary based on {len(news_info["artikel"])} news articles")
    return news_info

def consider_rollback(saved_candidates):
    # helper function to check if gnews has become unresponsive, and roll back news update candidates if so
    # TODO: this logic needs a rework. It's not good enough to just save a fixed number of update candidates. Have to make sure
    # that if there are X update candidates for a given law, all (or none) of them are rolled back.
    global no_news_found 

    test_result_count = 0
    delay = 64

    for retry in range(8):
        try:
            test_gn = GNews(language='de', country='DE')
            test_gn.start_date = (2024, 1, 1)
            test_gn.end_date = (2025, 1, 1)
            test_query = test_gn.get_news("Selbstbestimmungsgesetz")
            test_result_count = len(test_query)
        except Exception as e:
            test_result_count = 0
        
        if test_result_count >= 100:
            break

        delay *= 2
        
        print(f"Google News is unresponsive, retrying in {delay} seconds.")
        time.sleep(delay)
        

    if test_result_count < 100:
        error_message = f"No news found for {NEWS_UPDATE_CANDIDATES_ROLLBACK_COUNT * 3} queries in a row, test query only returned {test_result_count} results.\n"
        try:
            for original in saved_candidates:
                got_deleted = (candidate := db.session.query(NewsUpdateCandidate).filter(NewsUpdateCandidate.id == original.id).one_or_none()) is None
                candidate = candidate or NewsUpdateCandidate()
                candidate.last_update = original.last_update
                candidate.next_update = original.next_update
                candidate.update_count = original.update_count
                candidate.position = original.position
                if got_deleted:
                    db.session.add(candidate)
            db.session.commit()
            error_message += f"Successfully rolled back {len(saved_candidates)} news update candidates. No further action is required\n"
        except Exception as e:
            error_message += f"Error rolling back news update candidates: {e}\nManual rollback required\n"
        finally:
            error_message += "Affected candidates:\n"
            error_message += "\n".join(f"candidate id: {original.id}, positions id: {original.positions_id}, last update: {original.last_update}, next update: {original.next_update}, update count: {original.update_count}" for original in saved_candidates)
            error_message += f"\nExiting daily update at {datetime.datetime.now()}"
            report_error("Google News is unresponsive", error_message, True)
    else:
        no_news_found = 0

def generate_search_queries(client, law):
    shorthand = extract_shorthand(law.titel) if law.titel.endswith(")") else ""
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
        print(f"Error generating search query. Error: {e}. AI response: {ai_response}.")
        return None
    
    if shorthand and shorthand not in queries:
        queries.insert(0, shorthand)
    
    return queries

def get_structured_data_from_ai(client, messages, schema=None, subfield=None):
    # models = ['deepseek/deepseek-r1', 'deepseek/deepseek-chat', 'openai/gpt-4o-2024-11-20']
    models = ['deepseek/deepseek-r1']
    delay = 1

    for retry in range(13):
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
        
        try:
            ai_response = response.choices[0].message.content or response.choices[0].message.model_extra["reasoning"]
            ai_response = re.sub(r"<think>.*?</think>", "", ai_response, flags=re.DOTALL)
            ai_response = re.sub(r"```json\n(.*?)\n```", r"\1", ai_response, flags=re.DOTALL)
            ai_response = json.loads(ai_response).get(subfield, None) if subfield else json.loads(ai_response)
            return ai_response
        
        except Exception as e:
            print(f"Could not parse AI response {ai_response}\nFrom: {response.choices[0].message.content}\n\n Error: {e}. Retrying in {delay} seconds.")
            time.sleep(delay)
            delay *= 2
    
    report_error("Error getting structured data from AI", f"Could not get structured data from AI. Time: {datetime.datetime.now()}, Messages: {messages}. Schema: {schema}. Subfield: {subfield}.", True)
        

def get_text_data_from_ai(client, messages):
    # models = ['deepseek/deepseek-r1', 'deepseek/deepseek-chat', 'openai/gpt-4o-2024-11-20']
    models = ['deepseek/deepseek-r1']
    delay = 1

    for retry in range(13):
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

    report_error("Error getting structured data from AI", f"Could not get text data from AI. Time: {datetime.datetime.now()}, Messages: {messages}.", True)
    
    
def extract_shorthand(titel):
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

def update_law_in_es(law):
    try:
        es_law = es.get(index=ES_LAWS_INDEX, id=law.id)
        if law.titel == es_law['_source'].get('titel') and law.abstract == es_law["_source"].get('abstract'):
            return
        
    except NotFoundError:
        pass
    
    es.index(index=ES_LAWS_INDEX, id=law.id, body={
        'titel': law.titel,
        'abstract': law.abstract
    })

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
            connection.sendmail(ERROR_MAIL_ADDRESS, DEVELOPER_MAIL_ADDRESS, f"Subject: {subject}\n\n{message}")
            connection.close()
    except Exception as e:
        print(f"CRITICAL: Failed to report critical error via email. Error: {e}. Message: {subject}\n{message}")

    if terminate:
        set_update_active(False)
        os._exit(1)

if __name__ == "__main__":
    daily_update()
