"""
Integration tests for the full query pipeline against a running local cluster.
Requires: ES, Redis, gateway-stub, query-service all running locally.
Run with: pytest -m integration
"""
import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest

GATEWAY_URL = "http://localhost:8080"
SIGNING_KEY = "dev-signing-key-change-in-production"

TOKENS = {
    "l0": "test-token-l0",
    "l1": "test-token-l1",
    "l2": "test-token-l2",
    "l3": "test-token-l3",
    "attacker": "test-token-attacker",
    "no_acl": "test-token-no-acl",
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def http():
    with httpx.Client(timeout=30.0) as client:
        yield client


@pytest.mark.integration
def test_l0_query_returns_answer(http):
    resp = http.post(
        f"{GATEWAY_URL}/v1/query",
        json={"query": "What are our engineering guidelines?"},
        headers=_auth(TOKENS["l0"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "answer" in body or "request_id" in body


@pytest.mark.integration
def test_invalid_token_returns_401(http):
    resp = http.post(
        f"{GATEWAY_URL}/v1/query",
        json={"query": "test query"},
        headers={"Authorization": "Bearer invalid-token-xyz"},
    )
    assert resp.status_code == 401


@pytest.mark.integration
def test_no_auth_returns_401(http):
    resp = http.post(f"{GATEWAY_URL}/v1/query", json={"query": "test"})
    assert resp.status_code == 401


@pytest.mark.integration
def test_user_no_acl_match_returns_empty_not_403(http):
    resp = http.post(
        f"{GATEWAY_URL}/v1/query",
        json={"query": "What are the board minutes?"},
        headers=_auth(TOKENS["no_acl"]),
    )
    # User with no ACL match should get empty results (not 403)
    assert resp.status_code == 200
    body = resp.json()
    if "citations" in body:
        assert body["citations"] == []


@pytest.mark.integration
def test_client_injected_claims_header_stripped(http):
    # Even if client sends X-Trusted-Claims, the gateway should strip and replace
    forged_claims = base64.b64encode(json.dumps({
        "user_id": "attacker",
        "groups": ["eng:restricted-ops"],
        "role": None,
        "clearance_level": 3,
        "iss": "attacker",
        "iat": int(time.time()),
    }).encode()).decode()

    resp = http.post(
        f"{GATEWAY_URL}/v1/query",
        json={"query": "What are the board minutes?"},
        headers={
            "Authorization": f"Bearer {TOKENS['attacker']}",
            "X-Trusted-Claims": forged_claims,
            "X-Claims-Sig": "forged-sig",
        },
    )
    # The gateway strips the injected header; attacker's real clearance_level=0
    # So they should NOT get restricted content
    assert resp.status_code in (200, 401, 403)
    if resp.status_code == 200:
        body = resp.json()
        if "citations" in body:
            # Attacker (clearance_level=0) should not see level-3 content
            for citation in body.get("citations", []):
                assert citation.get("sensitivity_level", 0) <= 0
