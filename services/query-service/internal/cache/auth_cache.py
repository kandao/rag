import json
import logging
import os
from datetime import datetime, timezone

import redis.asyncio as aioredis

from rag_common.models.user_context import UserContext

logger = logging.getLogger(__name__)

REDIS_HOST = os.environ.get("REDIS_HOST", "redis.retrieval-deps")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_AUTH_CACHE_TTL_S = int(os.environ.get("REDIS_AUTH_CACHE_TTL_S", "300"))
REDIS_DB_AUTH = 0


def _cache_key(claims_hash: str) -> str:
    return f"acl:{claims_hash}"


async def get_cached_user_context(
    redis_client: aioredis.Redis,
    claims_hash: str,
) -> UserContext | None:
    """Return cached UserContext from Redis DB0, or None on miss/error."""
    try:
        raw = await redis_client.get(_cache_key(claims_hash))
        if raw is None:
            return None
        data = json.loads(raw)
        return UserContext(**data)
    except Exception as exc:
        logger.warning("auth_cache.get failed", extra={"error": str(exc)})
        return None


async def set_cached_user_context(
    redis_client: aioredis.Redis,
    ctx: UserContext,
) -> None:
    """Write UserContext to Redis DB0 with TTL. Logs and swallows errors (non-critical)."""
    try:
        payload = ctx.model_dump()
        await redis_client.set(
            _cache_key(ctx.claims_hash),
            json.dumps(payload),
            ex=REDIS_AUTH_CACHE_TTL_S,
        )
    except Exception as exc:
        logger.warning("auth_cache.set failed", extra={"error": str(exc)})
