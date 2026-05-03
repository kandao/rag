import os

import redis.asyncio as aioredis

RATE_LIMIT_RPM = int(os.environ.get("GUARD_RATE_LIMIT_USER_RPM", "20"))
RATE_LIMIT_WINDOW_S = int(os.environ.get("GUARD_RATE_LIMIT_WINDOW_S", "60"))


async def check_rate_limit(redis_client: aioredis.Redis, user_id: str) -> bool:
    """Return True if the user is within the rate limit, False if exceeded.

    Falls back to True (allow) if Redis is unavailable.
    """
    key = f"guard_rl:{user_id}"
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, RATE_LIMIT_WINDOW_S)
        return count <= RATE_LIMIT_RPM
    except Exception:
        return True  # degrade gracefully; log upstream
