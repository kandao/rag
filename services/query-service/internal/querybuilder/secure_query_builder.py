import httpx
import redis.asyncio as aioredis

from rag_common.models.query import QueryContext
from rag_common.models.user_context import UserContext

from ..routing.router import RoutingDecision
from .bm25_only_query import build_bm25_only_query
from .embedding_client import get_query_embedding
from .hybrid_query import build_hybrid_query
from .query_validator import assert_acl_present


async def build(
    user_context: UserContext,
    query_ctx: QueryContext,
    routing: RoutingDecision,
    redis_client: aioredis.Redis,
    http_client: httpx.AsyncClient,
) -> list[tuple[str, dict]]:
    """Build ES query DSL for each target index. Returns [(index_name, es_query), ...]."""
    embedding = await get_query_embedding(
        query=query_ctx.raw_query,
        allow_knn=routing.allow_knn,
        target_indexes=routing.target_indexes,
        redis_client=redis_client,
        http_client=http_client,
    )

    results: list[tuple[str, dict]] = []
    for index in routing.target_indexes:
        if routing.allow_knn and embedding is not None:
            es_query = build_hybrid_query(user_context, query_ctx, embedding)
        else:
            es_query = build_bm25_only_query(user_context, query_ctx)

        assert_acl_present(es_query)
        results.append((index, es_query))

    return results
