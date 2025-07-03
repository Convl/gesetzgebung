from gesetzgebung.helpers import get_structured_data_from_ai
from gesetzgebung.models import GesetzesVorhaben
from gesetzgebung.updater.update_news import GENERATE_QUERIES_SCHEMA, QUERIES_SCHEMA_DUMPS


from openai import OpenAI

from gesetzgebung.updater.launch import logger


def extract_shorthand(titel: str) -> str:
    """Extract the shorthand (not the abbreviation) from a law's title. Probably better to do this with regex, but this works for now."""
    if titel.find("(") == -1 or not titel.endswith(")"):
        return ""

    shorthand_start = titel.rfind("(") + 1
    # (2. Betriebsrentenstärkungsgesetz) -> Betriebsrentenstärkungsgesetz
    while titel[shorthand_start].isdigit() or titel[shorthand_start] in {".", " "}:
        shorthand_start += 1

    # (NIS-2-Umsetzungs- und Cybersicherheitsstärkungsgesetz) -> Cybersicherheitsstärkungsgesetz
    shorthand_start = max(shorthand_start, titel.find("- und ", shorthand_start, len(titel) - 1) + len("- und "))

    # (Sportfördergesetz - SpoFöG) -> Sportfördergesetz
    shorthand_end = (
        titel.find(" - ", shorthand_start, len(titel) - 1)
        if titel.find(" - ", shorthand_start, len(titel) - 1) > 0
        else len(titel) - 1
    )

    # same thing, except with long dash
    shorthand_end = (
        titel.find(" – ", shorthand_start, len(titel) - 1)
        if titel.find(" – ", shorthand_start, len(titel) - 1) > 0
        else len(titel) - 1
    )

    shorthand = f"{titel[shorthand_start:shorthand_end]}*"
    return shorthand


def generate_search_queries(client: OpenAI, law: GesetzesVorhaben) -> list[str]:
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
            ["deepseek/deepseek-r1"],
            temperature=0.3,
            attempts=5,
            delay=30,
        )
        queries = [query for query in ai_response if query]

    except Exception as e:
        logger.critical(
            f"Error generating search query. Error: {e}. AI response: {ai_response}.",
            subject="Error generating search queries ",
        )
        return None

    if shorthand and shorthand not in queries:
        queries.insert(0, shorthand)

    return queries
