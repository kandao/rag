import hashlib
import json
import logging
import os

import redis.asyncio as aioredis

from rag_common.models.retrieval import CitationHint, RetrievalCandidate

logger = logging.getLogger(__name__)

RESULT_CACHE_TTL_S = int(os.environ.get("RESULT_CACHE_TTL_S", "60"))


def _query_hash(raw_query: str, target_indexes: list[str]) -> str:
    payload = raw_query + "|" + "|".join(sorted(target_indexes))
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_key(raw_query: str, acl_key: str, target_indexes: list[str]) -> str:
    qh = _query_hash(raw_query, target_indexes)
    return f"result:{qh}:{acl_key}"


async def get_cached_results(
    redis_client: aioredis.Redis,
    raw_query: str,
    acl_key: str,
    target_indexes: list[str],
) -> list[RetrievalCandidate] | None:
    try:
        key = _cache_key(raw_query, acl_key, target_indexes)
        raw = await redis_client.get(key)
        if raw is None:
            return None
        data = json.loads(raw)
        return [RetrievalCandidate(**item) for item in data]
    except Exception as exc:
        logger.warning("result_cache.get failed", extra={"error": str(exc)})
        return None


async def set_cached_results(
    redis_client: aioredis.Redis,
    raw_query: str,
    acl_key: str,
    target_indexes: list[str],
    candidates: list[RetrievalCandidate],
) -> None:
    if not candidates:
        return
    try:
        key = _cache_key(raw_query, acl_key, target_indexes)
        payload = json.dumps([c.model_dump() for c in candidates])
        await redis_client.set(key, payload, ex=RESULT_CACHE_TTL_S)
    except Exception as exc:
        logger.warning("result_cache.set failed", extra={"error": str(exc)})
