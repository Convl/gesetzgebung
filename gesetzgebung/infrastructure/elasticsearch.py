"""
Elasticsearch configuration and utilities for the Gesetzgebung application.
"""

import warnings

from elasticsearch7.exceptions import NotFoundError
from urllib3.exceptions import InsecureRequestWarning

from gesetzgebung.infrastructure.config import ES_LAWS_INDEX, es

# Suppress SSL warnings for Elasticsearch
warnings.filterwarnings("ignore", category=InsecureRequestWarning)


def update_law_in_es(law):
    """Update a law in the Elasticsearch index."""
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
