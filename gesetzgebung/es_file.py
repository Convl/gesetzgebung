# from elasticsearch import Elasticsearch
from elasticsearch7 import Elasticsearch
# from elasticsearch.exceptions import NotFoundError
from elasticsearch7.exceptions import NotFoundError
import os
import warnings
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

ES_HOST = os.environ.get("ES_HOST") or os.environ.get("LOCAL_ES_HOST")
ES_LAWS_INDEX = os.environ.get("ES_LAWS_INDEX") or os.environ.get("LOCAL_ES_LAWS_INDEX")

index_body = {
  "settings": {
      "index": {
        "max_ngram_diff": 18  
      },
    "analysis": {
      "analyzer": {
        "ngram_analyzer": {
          "tokenizer": "ngram_tokenizer",
          "filter": ["lowercase"]
        },
        "ngram_search": {
          "tokenizer": "lowercase"
        }
      },
      "tokenizer": {
        "ngram_tokenizer": {
          "type": "ngram",
          "min_gram": 3,
          "max_gram": 20,
          "token_chars": ["letter", "digit"]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "titel": {
        "type": "text",
        "analyzer": "ngram_analyzer",
        "search_analyzer": "ngram_search"
      },
      "abstract": {
        "type": "text",
        "analyzer": "ngram_analyzer",
        "search_analyzer": "ngram_search"
      }
    }
  }
}

# es = Elasticsearch(ES_HOST)
es = Elasticsearch(ES_HOST,
                   verify_certs=False,
                   headers={"x-elastic-product": "Elasticsearch"})

if not es.indices.exists(index=ES_LAWS_INDEX):
    es.indices.create(index=ES_LAWS_INDEX, body=index_body)

def update_law_in_es(law):
    try:
        es_law = es.get(index=ES_LAWS_INDEX, id=law.id)
        if law.titel == es_law["_source"].get("titel") and law.abstract == es_law["_source"].get("abstract"):
            return

    except NotFoundError:
        pass

    es.index(
        index=ES_LAWS_INDEX,
        id=law.id,
        body={"titel": law.titel, "abstract": law.abstract},
    )
