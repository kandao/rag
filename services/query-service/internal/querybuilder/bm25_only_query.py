import os

from rag_common.models.query import QueryContext
from rag_common.models.user_context import UserContext

from .acl_filter import SOURCE_FIELDS, build_acl_filters
from .hybrid_query import BM25_SEARCH_FIELDS, _metadata_filters

QUERY_RESULT_SIZE = int(os.environ.get("QUERY_RESULT_SIZE", "100"))


def build_bm25_only_query(user_context: UserContext, query_ctx: QueryContext) -> dict:
    """Build BM25-only query for cross-tier searches where kNN is disabled."""
    acl = build_acl_filters(user_context)
    meta = _metadata_filters(query_ctx)

    return {
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query_ctx.raw_query,
                            "fields": BM25_SEARCH_FIELDS,
                        }
                    }
                ],
                "filter": acl + meta,
            }
        },
        "size": QUERY_RESULT_SIZE,
        "_source": SOURCE_FIELDS,
    }
