import logging
from dataclasses import dataclass
from typing import Literal

import redis.asyncio as aioredis

from internal.audit.event_builder import truncate_query_fragment

from .enumeration_detector import detect_enumeration
from .injection_detector import detect_injection
from .rate_limiter import check_rate_limit

logger = logging.getLogger(__name__)


class GuardError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.http_status = http_status
        super().__init__(message)


@dataclass
class GuardResult:
    risk_signal: Literal["none", "low", "medium", "high"]


async def check(
    redis_client: aioredis.Redis,
    user_id: str,
    query: str,
) -> GuardResult:
    """Run all 3 guard checks. Raises GuardError to block; returns GuardResult to allow."""

    # [1] Rate limit
    within_limit = await check_rate_limit(redis_client, user_id)
    if not within_limit:
        raise GuardError("ERR_GUARD_RATE_LIMIT", "Rate limit exceeded", http_status=429)

    # [2] Injection detection
    injection = detect_injection(query)
    if injection.risk_level == "high":
        logger.warning(
            "Guard: injection detected",
            extra={"user_id": user_id, "pattern_id": injection.pattern_id,
                   "query_fragment": truncate_query_fragment(query)},
        )
        raise GuardError("ERR_GUARD_INJECTION_DETECTED", "Query blocked: injection risk", http_status=400)

    # [3] Enumeration detection
    try:
        enum_detected = await detect_enumeration(redis_client, user_id, query)
    except Exception:
        enum_detected = False

    if enum_detected:
        logger.warning("Guard: enumeration suspected", extra={"user_id": user_id})
        raise GuardError("ERR_GUARD_ENUMERATION_DETECTED", "Enumeration pattern detected", http_status=429)

    risk: Literal["none", "low", "medium", "high"] = (
        "medium" if injection.risk_level == "medium" else "none"
    )
    return GuardResult(risk_signal=risk)
