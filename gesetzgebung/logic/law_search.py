from gesetzgebung.infrastructure.es_file import es, ES_LAWS_INDEX


def search_laws(query):
    if query == "":
        return []

    response = es.search(
        index=ES_LAWS_INDEX,
        body={
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["titel^3", "abstract"],
                    "type": "best_fields",  # maybe experiment with most_fields or cross_fields, also maybe add 'fuzziness': 'AUTO'
                }
            },
            "size": 10,
        },
    )

    suggestions = [{"id": hit["_id"], "titel": hit["_source"]["titel"]} for hit in response["hits"]["hits"]]
    return suggestions
