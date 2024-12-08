from gesetzgebung.config import app, db, es, scheduler
from gesetzgebung.models import get_all_laws

ES_LAWS_INDEX = "laws_index"

with app.app_context():
    db.create_all() # TODO remove this before production
    laws = get_all_laws()

index_body = {
    "settings": {
        "analysis": {
            "analyzer": {
                "autocomplete_analyzer": {
                    "type": "custom",
                    "tokenizer": "edge_ngram",
                    "filter": ["lowercase"]
                },
                "standard_analyzer": {
                    "type": "standard"
                }
            },
            "tokenizer": {
                "edge_ngram": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "titel": {
                "type": "text",
                "analyzer": "autocomplete_analyzer",
                "search_analyzer": "autocomplete_analyzer"
            },
            "abstract": {
                "type": "text",
                "analyzer": "autocomplete_analyzer",
                "search_analyzer": "autocomplete_analyzer"
            }
        }
    }
}

# TODO: Good idea to only add laws if the index itself does not exist?
# TODO Change es indexing / search method, right now e.g. "wahl" finds "Gesetz zur Änderung des Bundeswahlgesetzes", but "wahlg" does not.
if not es.indices.exists(index=ES_LAWS_INDEX):
    # es.indices.create(index=ES_LAWS_INDEX, body=index_body)
    for law in laws:
        es.index(index=ES_LAWS_INDEX, id=law.id, document={'titel': law.titel, 'abstract': law.abstract})

from gesetzgebung import routes

