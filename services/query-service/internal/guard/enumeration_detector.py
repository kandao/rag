import os
import re

import redis.asyncio as aioredis

SIMILARITY_THRESHOLD = float(os.environ.get("GUARD_ENUM_SIMILARITY_THRESHOLD", "0.85"))
WINDOW_SIZE = int(os.environ.get("GUARD_ENUM_WINDOW_SIZE", "10"))
HISTORY_TTL_S = int(os.environ.get("GUARD_ENUM_HISTORY_TTL_S", "300"))


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta and not tb:
        return 1.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union)


def _looks_sequential(queries: list[str]) -> bool:
    """Detect sequential enumeration via trailing numeric suffix (e.g. doc_1, vendor 2)."""
    if len(queries) < 3:
        return False
    nums = []
    for q in queries:
        m = re.search(r"[_\s](\d+)\s*$", q.strip())
        if m:
            nums.append(int(m.group(1)))
        else:
            return False
    diffs = [nums[i + 1] - nums[i] for i in range(len(nums) - 1)]
    return all(d == 1 for d in diffs)


def _avg_pairwise_similarity(queries: list[str]) -> float:
    if len(queries) < 2:
        return 0.0
    pairs = 0
    total = 0.0
    for i in range(len(queries)):
        for j in range(i + 1, len(queries)):
            total += _jaccard(queries[i], queries[j])
            pairs += 1
    return total / pairs if pairs else 0.0


async def detect_enumeration(
    redis_client: aioredis.Redis,
    user_id: str,
    current_query: str,
) -> bool:
    """Return True if an enumeration pattern is detected. Logs and returns False on Redis error."""
    history_key = f"guard_hist:{user_id}"

    try:
        raw_history = await redis_client.lrange(history_key, 0, WINDOW_SIZE - 1)
        history = [h.decode() if isinstance(h, bytes) else h for h in raw_history]
    except Exception:
        return False

    window = history + [current_query]

    detected = _looks_sequential(window) or _avg_pairwise_similarity(window) > SIMILARITY_THRESHOLD

    try:
        await redis_client.lpush(history_key, current_query)
        await redis_client.ltrim(history_key, 0, WINDOW_SIZE - 1)
        await redis_client.expire(history_key, HISTORY_TTL_S)
    except Exception:
        pass

    return detected
