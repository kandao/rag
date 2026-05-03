"""
Shared fixtures for HLD E2E / integration tests.

Requires a running local stack:
  - Elasticsearch at ES_URL (default http://localhost:9200)
  - Redis at REDIS_URL (default redis://localhost:6379)
  - Embedding service at EMBEDDING_URL (default http://localhost:8001)
  - Reranker service at RERANKER_URL (default http://localhost:8002)
  - Gateway + query service at GATEWAY_URL (default http://localhost:8080)

Run with: pytest -m e2e
"""
import os
import time
import base64
import hashlib
import hmac
import json

import httpx
import pytest

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
ES_URL = os.getenv("ES_URL", "http://localhost:9200")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
EMBEDDING_URL = os.getenv("EMBEDDING_URL", "http://localhost:8001")
RERANKER_URL = os.getenv("RERANKER_URL", "http://localhost:8002")

SIGNING_KEY = os.getenv("SIGNING_KEY", "dev-signing-key-change-in-production")

TOKENS = {
    "l0": "test-token-l0",
    "l1": "test-token-l1",
    "l1_b": "test-token-l1-b",
    "l2": "test-token-l2",
    "l3": "test-token-l3",
    "attacker": "test-token-attacker",
    "no_acl": "test-token-no-acl",
}

# Ground-truth dataset: (query, expected_chunk_id)
# Loaded from env or inline for local testing.
GROUND_TRUTH = [
    {"query": "What are the 2024 engineering guidelines?", "chunk_id": "eng-guide-2024-001", "index": "internal_index"},
    {"query": "engineering best practices version 2024", "chunk_id": "eng-guide-2024-001", "index": "internal_index"},
    {"query": "hr onboarding policy steps", "chunk_id": "hr-policy-2024-001", "index": "internal_index"},
    {"query": "employee onboarding procedure", "chunk_id": "hr-policy-2024-001", "index": "internal_index"},
    {"query": "product overview features", "chunk_id": "product-overview-001", "index": "public_index"},
]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def http():
    with httpx.Client(timeout=30.0) as client:
        yield client


@pytest.fixture(autouse=True)
def reset_guard_state():
    """Keep E2E tests independent from query guard history/rate-limit state."""
    try:
        import redis as sync_redis
        r = sync_redis.from_url(REDIS_URL)
        keys = list(r.scan_iter("guard_*"))
        if keys:
            r.delete(*keys)
    except Exception:
        pass


@pytest.fixture(scope="module")
def http_async():
    """For tests that need async HTTP."""
    import asyncio
    import httpx
    return httpx.AsyncClient(timeout=30.0)


def query_via_gateway(http_client: httpx.Client, token: str, query: str) -> dict:
    """Helper: POST /v1/query through the gateway and return the response body."""
    resp = http_client.post(
        f"{GATEWAY_URL}/v1/query",
        json={"query": query},
        headers=_auth(TOKENS[token]),
    )
    return resp


def get_chunk_ids(body: dict) -> list[str]:
    """Extract chunk_ids from a query response body."""
    return [c.get("chunk_id", "") for c in body.get("citations", [])]
