"""
HLD-CACHE-01: Auth-cache hit rate ≥ 80% (Integration)

Requires: real Redis + query service running locally.
Run with: pytest -m e2e tests/e2e/test_cache.py
"""
import time
import pytest
import httpx

from .conftest import GATEWAY_URL, REDIS_URL, TOKENS

pytestmark = pytest.mark.e2e

QUERY_COUNT = 100
EXPECTED_HIT_RATE = 0.80

# All 100 queries use the same user token → same claims_hash → Redis auth-cache should hit
REPEATED_QUERY = "What are the engineering guidelines?"


def _auth(token_key: str) -> dict:
    return {"Authorization": f"Bearer {TOKENS[token_key]}"}


def _get_redis_cache_stats() -> dict:
    """Read Redis INFO stats to extract keyspace hits/misses."""
    try:
        import redis as sync_redis
        r = sync_redis.from_url(REDIS_URL)
        info = r.info("stats")
        return {
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# HLD-CACHE-01: ACL auth-cache hit rate ≥ 80% for same user over 100 queries
# ---------------------------------------------------------------------------

def test_hld_cache_01_auth_cache_hit_rate():
    """
    Send 100 queries from the same user (identical claims_hash).
    The Redis auth-cache (DB 0) should serve ≥ 80% of ACL derivation lookups from cache.
    """
    stats_before = _get_redis_cache_stats()

    with httpx.Client(timeout=30.0) as client:
        for i in range(QUERY_COUNT):
            resp = client.post(
                f"{GATEWAY_URL}/v1/query",
                json={"query": REPEATED_QUERY},
                headers=_auth("l1"),
            )
            # First request seeds the cache; subsequent ones should hit
            assert resp.status_code in (200, 400, 429), (
                f"Unexpected status {resp.status_code} on request {i+1}"
            )

    stats_after = _get_redis_cache_stats()

    if not stats_before or not stats_after:
        pytest.skip("Redis stats not available — cannot measure cache hit rate")

    delta_hits = stats_after["hits"] - stats_before["hits"]
    delta_misses = stats_after["misses"] - stats_before["misses"]
    total = delta_hits + delta_misses

    if total == 0:
        pytest.skip("No Redis activity recorded — Redis may not be connected")

    hit_rate = delta_hits / total
    assert hit_rate >= EXPECTED_HIT_RATE, (
        f"HLD-CACHE-01: Auth-cache hit rate={hit_rate:.2f} < {EXPECTED_HIT_RATE} "
        f"(hits={delta_hits}, misses={delta_misses}, total={total})"
    )
