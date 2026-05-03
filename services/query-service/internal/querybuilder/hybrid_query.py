import os

from rag_common.models.query import QueryContext
from rag_common.models.user_context import UserContext

from .acl_filter import SOURCE_FIELDS, build_acl_filters

VECTOR_BOOST = float(os.environ.get("HYBRID_QUERY_VECTOR_BOOST", "0.7"))
BM25_BOOST = float(os.environ.get("HYBRID_QUERY_BM25_BOOST", "0.3"))
KNN_K = int(os.environ.get("HYBRID_QUERY_K", "100"))
KNN_NUM_CANDIDATES = int(os.environ.get("HYBRID_QUERY_NUM_CANDIDATES", "200"))
QUERY_RESULT_SIZE = int(os.environ.get("QUERY_RESULT_SIZE", "100"))


def _metadata_filters(query_ctx: QueryContext) -> list[dict]:
    filters = []
    if query_ctx.topic:
        filters.append({"term": {"topic": query_ctx.topic}})
    if query_ctx.doc_type:
        filters.append({"term": {"doc_type": query_ctx.doc_type}})
    return filters


def build_hybrid_query(
    user_context: UserContext,
    query_ctx: QueryContext,
    query_embedding: list[float],
) -> dict:
    """Build hybrid BM25 + kNN query with ACL filter in BOTH bool.filter and knn.filter."""
    acl = build_acl_filters(user_context)
    meta = _metadata_filters(query_ctx)
    all_filters = acl + meta

    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query_ctx.raw_query,
                            "fields": ["content"],
                            "boost": BM25_BOOST,
                        }
                    }
                ],
                "filter": all_filters,
            }
        },
        "knn": {
            "field": "vector",
            "query_vector": query_embedding,
            "k": KNN_K,
            "num_candidates": KNN_NUM_CANDIDATES,
            "boost": VECTOR_BOOST,
            "filter": {"bool": {"filter": all_filters}},
        },
        "size": QUERY_RESULT_SIZE,
        "_source": SOURCE_FIELDS,
    }
