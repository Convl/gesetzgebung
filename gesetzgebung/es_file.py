from elasticsearch import Elasticsearch
import os

ES_HOST = "http://localhost:9200"
ES_USER = os.environ.get("ES_USER")
ES_PASSWORD = os.environ.get("ES_PASSWORD")
ES_LAWS_INDEX = "laws_index"

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

es = Elasticsearch("http://localhost:9200", basic_auth=(ES_USER, ES_PASSWORD))

if not es.indices.exists(index=ES_LAWS_INDEX):
    es.indices.create(index=ES_LAWS_INDEX, body=index_body)