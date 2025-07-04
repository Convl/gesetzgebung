import datetime
import time
import os
from gesetzgebung.infrastructure.models import *
from gesetzgebung.logic.law_parser import parse_law
from gesetzgebung.helpers import get_structured_data_from_ai, get_text_data_from_ai, exp_backoff, ExpBackoffException
from gesetzgebung.infrastructure.logger import log_indent
from gesetzgebung.updater.logger import logger
from gesetzgebung.updater.query_generator import generate_search_queries
from typing import List, Optional
from dataclasses import dataclass, field

import json
from openai import OpenAI
import newspaper
from gnews import GNews
from googlenewsdecoder import gnewsdecoder
from itertools import groupby

SUMMARY_LENGTH = 700
IDEAL_ARTICLE_COUNT = 5
MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY = 3
MINIMUM_ARTICLE_LENGTH = 3000
MAXIMUM_ARTICLE_LENGTH = 20000
GNEWS_ATTEMPTS = 5
GNEWS_RETRY_DELAY = 300
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


def update_news_update_candidates() -> None:
    """Function to update NewsUpdateCandidates. Sits at the root of the news update hierarchy and should be launched after update_laws() with app.app_context() if __name__ == __main__.
    Process for updating news articles / creating summaries:
    - This is a bit more complex than might seem necessary, because it needs to also work when first populating the database.
    - Check all NewsUpdateCandidates (i.e. Vorgangspositionen that haven't had a news summary added in a while, or at all)
    - If a NewsUpdateCandidate is new, it receives its first update, any older NewsUpdateCandidates belonging to the same law receive their final update and are removed from the list
    - If no new NewsUpdateCandidates were added for a given law, existing ones get updated periodically in increasing intervals
    - Updating means that news articles for the relevant timeframe will be searched, and a summary will be created if enough (new) articles are found.
    """

    client = OpenAI(base_url=AI_ENDPOINT, api_key=AI_API_KEY)
    gn = GNews(language="de", country="DE")
    now = datetime.datetime.now().date()

    # create a candidate_groups list of dicts that have law ids as keys, and a list of NewsUpdateCandidates corresponding to that law id, in reverse chronological order, as values (if this runs daily, there should only be 1-2 NewsUpdateCandidate per law, but there will be many when first populating the database). We need not worry about several NewsUpdateCandidates of a given law being on the same date, as this is prevented in update_positionen when adding NewsUpdateCandidates
    all_candidates = (
        db.session.query(NewsUpdateCandidate)
        .join(Vorgangsposition)
        .join(GesetzesVorhaben)
        .order_by(GesetzesVorhaben.id, Vorgangsposition.datum)
        .all()
    )
    candidate_groups = {
        law_id: sorted(list(group), key=lambda c: c.position.datum, reverse=True)
        for law_id, group in groupby(all_candidates, key=lambda c: c.position.gesetz.id)
    }

    # as we crud the NewsUpdateCandidates, we need to save X amount of them in case we ever need to roll back after discovering that gnews has been blocking us.
    saved_for_rollback = []

    for law_id, candidates in candidate_groups.items():
        logger.info(
            f"*** Starting news update for law with id {law_id}, update candidate ids: {[c.id for c in candidates]} ***"
        )
        law = get_law_by_id(law_id)

        # we use the parse_law function with display=False from the webapp here to get some more info to later feed to the llm about the Vorgangspositionen that mark the start and end of a given timespan.
        infos = parse_law(law, display=False, use_session=False)

        # The function for summarizing news articles informs the LLM about the Vorgangspositionen after / before which the news articles have been published. Since there is no Vorgangsposition after the most recent one, we create a dummy node to cover this time period.
        completion_state = (
            "Das Ereignis, das den Start dieses Zeitraums markiert, markiert zugleich den erfolgreichen Abschluss des Gesetzgebungsverfahrens."
            if any(info["marks_success"] for info in infos)
            else (
                "Das Ereignis, das den Start dieses Zeitraums markiert, markiert zugleich das Scheitern des Gesetzgebungsverfahrens."
                if any(info["marks_failure"] for info in infos)
                else "Das Ereignis, das den Start dieses Zeitraums markiert, ist das momentan aktuellste im laufenden Gesetzgebungsverfahren."
            )
        )
        dummy_info = {
            "datetime": now,
            "ai_info": f"{completion_state} Die mit diesem Zeitraum verknüpften Nachrichtenartikel reichen somit bis zum heutigen Tag.",
        }

        # There is a sublist of NewsUpdateCandidates for each law saved for rollback. We can safely keep popping these from the start of the queue as long as the remaining sublists contain more NewsUpdateCandidates than the number of times gnews returned 0. This will pop all sublists if no_news_found == 0, as sum() of an empty generator also == 0
        while (
            saved_for_rollback
            and sum(len(candidates_of_a_given_law) for candidates_of_a_given_law in saved_for_rollback[1:])
            >= no_news_found
        ):
            saved_for_rollback.pop(0)

        # New NewsUpdateCandidate sublist for new law
        saved_for_rollback.append([])

        # work through NewsUpdateCandidates of a law, starting with the most recent. Get info for it and for the next one up (= dummy info in case of most recent NewsUpdateCandidate)
        for i, candidate in enumerate(candidates):
            position = candidate.position
            info = next(inf for inf in infos if inf["id"] == position.id)
            next_info = (
                next(inf for inf in infos if inf["id"] == candidates[i - 1].position.id) if i > 0 else dummy_info
            )

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
                next_interval = next(
                    (interval for interval in NEWS_UPDATE_INTERVALS if interval > position_age),
                    NEWS_UPDATE_INTERVALS[-1],
                )
                candidate.next_update = now + next_interval
                candidate.update_count += 1
            db.session.commit()


@log_indent
def update_queries(client: OpenAI, law: GesetzesVorhaben, now: datetime.date) -> None:
    """Wrapper around generate_search_queries, which checks if the next update is due and assigns the new queries to the law if so"""
    last_updated = law.queries_last_updated or datetime.date(1900, 1, 1)
    if now - last_updated > QUERY_UPDATE_INTERVALS[min(law.query_update_counter, len(QUERY_UPDATE_INTERVALS) - 1)]:
        law.queries = generate_search_queries(client, law)
        if law.queries:
            law.queries_last_updated = now
            law.query_update_counter += 1
        else:
            logger.critical(
                f"CRITICAL: No search queries available for law with id {law.id}, terminating.",
                subject="Could not generate search queries.",
            )


@log_indent
def update_news(
    client: OpenAI,
    gn: GNews,
    position: Vorgangsposition,
    infos: list[dict],
    saved_for_rollback: list[SavedNewsUpdateCandidate],
    law: GesetzesVorhaben,
) -> None:
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
def get_news(
    client: OpenAI,
    gn: GNews,
    position: Vorgangsposition,
    infos: list[dict],
    saved_for_rollback: list[SavedNewsUpdateCandidate],
    law: GesetzesVorhaben,
) -> NewsInfo:
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
    used_article_urls = (
        db.session.query(NewsArticle.url)
        .join(NewsSummary, NewsArticle.summary_id == NewsSummary.id)
        .join(Vorgangsposition, NewsSummary.positions_id == Vorgangsposition.id)
        .join(GesetzesVorhaben, Vorgangsposition.vorgangs_id == GesetzesVorhaben.id)
        .filter(GesetzesVorhaben.id == law.id)
        .all()
    )

    logger.debug(
        f"Retrieving news for law: {law.titel} from {news_info.start_event} ({start_date}) to {news_info.end_event} ({end_date})"
    )

    no_news_for_this_candidate = True
    for query_counter, query in enumerate(law.queries):
        time.sleep(1)

        # If no news have been found for a while, check if it is just a coincidence, or if gnews is blocking us
        if no_news_found >= NEWS_UPDATE_CANDIDATES_ROLLBACK_COUNT:
            consider_rollback(saved_for_rollback)

        # if there are no news for this query, continue with the next
        if not (gnews_response := gn.get_news(query)):
            logger.debug(
                f"No news found for query {query_counter+1}/{len(law.queries)}: {query}, start date: {gn.start_date}, end date: {gn.end_date}"
            )
            continue
        else:
            no_news_for_this_candidate = False

        num_found = len(gnews_response)
        logger.debug(
            f"found {num_found} articles for query {query_counter+1}/{len(law.queries)}: {query}, start date: {gn.start_date}, end date: {gn.end_date}"
        )

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
                    [
                        {"index": i, "titel": article.get("title", "Titel nicht verfügbar")}
                        for i, article in enumerate(gnews_response)
                    ],
                    ensure_ascii=False,
                ),
                "role": "user",
            },
        ]

        # pop all irrelevant articles from gnews_response
        try:
            ai_response = get_structured_data_from_ai(
                client,
                evaluate_results_messages,
                EVALUATE_RESULTS_SCHEMA,
                "artikel",
                ["deepseek/deepseek-r1"],
                0.3,
                5,
                30,
            )

            for i in range(len(gnews_response) - 1, -1, -1):
                if ai_response[i]["passend"] in {0, "0"}:
                    gnews_response.pop(i)

        except Exception as e:
            logger.critical(
                f"Error evaluating search results: {e}. Evaluate results messages: {evaluate_results_messages}, ai response: {ai_response}",
                subject="Error evaluating search results",
            )
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
        logger.debug(
            f"Eliminated {num_found - len(gnews_response)} irrelevant articles for query: {query}. {len(gnews_response)} relevant articles remain."
        )

        saved_for_summary = 0
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
                logger.error(
                    f"Unknown Error {e} while decoding URL {article['url']} of article {article}",
                    subject="Error decoding URL",
                )
                continue

            # skip the article if it has already been processed, either from another search query for the current timespan (first check) or in a different timespan pertaining to the same law (second check, see above)
            if (
                any(article["url"] == existing_article["url"] for existing_article in news_info.article_data)
                or article["url"] in used_article_urls
            ):
                continue

            # skip the article if we cannot download / parse it
            try:
                news_article = newspaper.article(article["url"], language="de")
            except Exception as e:
                logger.info(f"Error parsing news article: {str(e)}")
                continue

            # skip the article if it is too short / long / otherwise invalid
            if (
                not news_article.is_valid_body()
                or len(news_article.text) < MINIMUM_ARTICLE_LENGTH
                or len(news_article.text) > MAXIMUM_ARTICLE_LENGTH
            ):
                continue

            # sometimes articles that got updated later are included in the response from Google News. This filters out some of those, though still not all.
            if not news_article.publish_date or news_article.publish_date.date() >= end_date:
                continue

            # add the article's text and associated data to our news_info object
            news_info.artikel.append(news_article.text)
            news_info.article_data.append(article)
            saved_for_summary += 1

        logger.debug(
            f"Added {saved_for_summary} articles for summary creation. {len(gnews_response) - saved_for_summary} articles were discarded due to e.g. issues with length, failure to download, etc."
        )

    # if none of the queries for this candidate produced a hit, increase no_news_found counter
    if no_news_for_this_candidate:
        no_news_found += 1
    else:
        no_news_found = 0

    return news_info


@log_indent
def generate_summary(
    client: OpenAI, news_info: NewsInfo, position: Vorgangsposition, law: GesetzesVorhaben
) -> NewsInfo:
    """Generates a summary for a given Vorgangsposition from a NewsInfo object"""

    # if we don't have enough articles, return without creating a summary
    if len(news_info.artikel) < MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY:
        logger.info(
            f"Only found {len(news_info.artikel)} usable articles, need {MINIMUM_ARTICLES_TO_DISPLAY_SUMMARY} to display summary."
        )
        return news_info

    # if a summary already exists
    if position.summary:
        # ...don't make a new one if the old one was based on more articles
        if len(news_info.artikel) < len(position.summary.articles):
            logger.info(
                f"Already had a summary based on {len(position.summary.articles)} articles, only have {len(news_info.artikel)} articles now, no update to the summary is needed."
            )
        # ... or if the old one had a sufficient number of hits, and we don't have at least 1.5x as many
        elif (
            position.summary.articles_found >= IDEAL_ARTICLE_COUNT
            and news_info.relevant_hits < position.summary.articles_found * 1.5
        ):
            logger.info(
                f"Already had a summary based on {position.summary.articles_found} relevant hits, only have {news_info.relevant_hits} relevant hits now, no update to the summary is needed."
            )
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
    logger.info(
        f"Generated summary for law: {law.titel} from {news_info.start_event} to {news_info.end_event} based on {len(news_info.artikel)} news articles"
    )
    return news_info


def consider_rollback(saved_for_rollback: list[SavedNewsUpdateCandidate]) -> None:
    """Checks if gnews has become unresponsive. If so, rolls back news update candidates, then tries to restore responsiveness with exponential backoff and terminates if this, too, is unsuccesful."""

    def rollback_candidates():
        """Rolls back saved NewsUpdateCandidates if the first run of check_if_gnews_is_unresponsive fails. Passed as a callback to exp_backoff"""
        error_message = (
            f"Starting rollback of saved NewsUpdateCandidates because gnews was unresponsive on first test query.\n"
        )
        try:
            for candidates_of_a_given_law in saved_for_rollback:
                for original in candidates_of_a_given_law:
                    # recreate candidate if it has been deleted (forgot to do this in earlier versions, likely leading to some odd downstream behaviour)
                    if (
                        candidate := db.session.query(NewsUpdateCandidate)
                        .filter(NewsUpdateCandidate.id == original.id)
                        .one_or_none()
                    ) is None:
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
                [
                    f"candidate id: {original.id}, positions id: {original.positions_id}, last update: {original.last_update}, next update: {original.next_update}, update count: {original.update_count}"
                    for candidates_of_a_given_law in saved_for_rollback
                    for original in candidates_of_a_given_law
                ]
            )
            error_message += f"\nExiting daily update at {datetime.datetime.now()}"
            logger.error(error_message, subject="Google News is unresponsive")

    @exp_backoff(
        attempts=GNEWS_ATTEMPTS,
        base_delay=GNEWS_RETRY_DELAY,
        terminate_on_final_failure=True,
        callback_on_first_failure=rollback_candidates,
        pass_attempt_count=True,
    )
    def check_if_gnews_is_unresponsive(attempt=0):
        """Checks to see if gnews is unresponsive with a test query that should return 100 hits (actually much more, but it is capped at 100).
        Decorated such that candidates will be rolled back after the test query fails once, then further attempts at restoring responsiveness are made with exponential backoff
        """
        try:
            test_gn = GNews(language="de", country="DE")
            test_gn.start_date = (2024, 1, 1)
            test_gn.end_date = (2025, 1, 1)
            test_query = test_gn.get_news("Selbstbestimmungsgesetz")
            test_result_count = len(test_query)
        except Exception as e:
            raise ExpBackoffException(f"Querying google news failed with error: {e} on attempt {attempt}.")
        if test_result_count < 100:
            raise ExpBackoffException(
                f"Google news test query only returned {test_result_count} results on attempt {attempt}."
            )
        else:
            logger.info(f"Gnews returned the expected {test_result_count} results on attempt {attempt}")

    global no_news_found
    logger.info(f"Checking if gnews is unresponsive, after receiving no news for {no_news_found} queries in a row")
    check_if_gnews_is_unresponsive()

    # if execution reaches this point, gnews is responsive (again), so reset the counter
    no_news_found = 0


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
