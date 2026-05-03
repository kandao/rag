import asyncio
import logging
import os

import redis.asyncio as aioredis
from elasticsearch import AsyncElasticsearch

from rag_common.models.retrieval import RetrievalCandidate
from rag_common.models.user_context import UserContext

from .es_client import search_index
from .merger import dedup_and_cap, normalize_scores
from .result_cache import get_cached_results, set_cached_results

logger = logging.getLogger(__name__)

MAX_CANDIDATES_TOTAL = int(os.environ.get("MAX_CANDIDATES_TOTAL", "200"))

RETRIEVAL_FAILED_CODE = "ERR_RETRIEVAL_FAILED"


class RetrievalError(Exception):
    code = RETRIEVAL_FAILED_CODE


async def execute(
    per_index_queries: list[tuple[str, dict]],
    user_context: UserContext,
    raw_query: str,
    es_client: AsyncElasticsearch,
    redis_client: aioredis.Redis,
) -> list[RetrievalCandidate]:
    """Fan out, deduplicate, normalize, cache, and return authorized candidates."""
    target_indexes = [idx for idx, _ in per_index_queries]

    cached = await get_cached_results(redis_client, raw_query, user_context.acl_key, target_indexes)
    if cached is not None:
        return cached

    tasks = [search_index(es_client, idx, query) for idx, query in per_index_queries]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    candidates_by_index: dict[str, list[RetrievalCandidate]] = {}
    for (index, _), result in zip(per_index_queries, responses):
        if isinstance(result, Exception):
            logger.error("ES search failed", extra={"index": index, "error": str(result)})
            if user_context.effective_clearance >= 2:
                raise RetrievalError(f"ES search failed on {index}: {result}")
            continue
        candidates_by_index[index] = result

    normalized = normalize_scores(candidates_by_index)
    final = dedup_and_cap(normalized, MAX_CANDIDATES_TOTAL)

    await set_cached_results(redis_client, raw_query, user_context.acl_key, target_indexes, final)
    return final
