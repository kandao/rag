import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from schemas import Claims, MockUser
import main as gw_main


def _make_user(token: str, clearance: int = 1) -> MockUser:
    return MockUser(
        token=token,
        claims=Claims(
            user_id="u1", groups=["eng:public"], role=None,
            clearance_level=clearance, iss="gateway-stub", iat=0,
        ),
    )


@pytest.fixture()
def gw():
    """Yield (TestClient, mock_http). Override app.state.http AFTER lifespan runs."""
    gw_main._users.clear()
    gw_main._users["valid-token"] = _make_user("valid-token", clearance=1)

    mock_resp = MagicMock()
    mock_resp.content = b'{"answer": "ok"}'
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}

    http = AsyncMock()
    http.request = AsyncMock(return_value=mock_resp)
    http.aclose = AsyncMock()

    with TestClient(gw_main.app, raise_server_exceptions=False) as c:
        gw_main.app.state.http = http  # Override after lifespan finishes startup
        yield c, http


def test_gw_02_unknown_token_returns_401(gw):
    """GW-02: Token not in registered users → 401 Invalid token."""
    client, _ = gw
    resp = client.post(
        "/v1/query",
        json={"query": "test"},
        headers={"Authorization": "Bearer unknown-token"},
    )
    assert resp.status_code == 401


def test_gw_02_missing_bearer_returns_401(gw):
    """GW-02: No Authorization header → 401 Missing Bearer token."""
    client, _ = gw
    resp = client.post("/v1/query", json={"query": "test"})
    assert resp.status_code == 401


def test_gw_04_client_injected_claims_header_stripped(gw):
    """GW-04: Client X-Trusted-Claims header stripped; gateway's signed claims used instead."""
    client, http = gw
    injected_value = "attacker-controlled-claims"

    client.post(
        "/v1/query",
        json={"query": "test"},
        headers={
            "Authorization": "Bearer valid-token",
            "X-Trusted-Claims": injected_value,
            "X-Claims-Sig": "forged-sig",
        },
    )

    forwarded_headers = http.request.call_args.kwargs.get("headers", {})
    assert forwarded_headers.get("x-trusted-claims") != injected_value
    assert "x-trusted-claims" in forwarded_headers


def test_gw_valid_token_proxies_with_signed_claims(gw):
    """Valid token → gateway adds signed x-trusted-claims and x-claims-sig headers."""
    client, http = gw
    resp = client.post(
        "/v1/query",
        json={"query": "What are the regulations?"},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert resp.status_code == 200
    forwarded_headers = http.request.call_args.kwargs.get("headers", {})
    assert "x-trusted-claims" in forwarded_headers
    assert "x-claims-sig" in forwarded_headers
    assert "authorization" not in forwarded_headers


def test_gw_05_placeholder():
    """GW-05: Rate limiting (429) not implemented in gateway-stub; enforced in query-service guard."""
    pytest.skip("Rate limit enforcement is in query-service, not gateway-stub")


def test_gw_06_placeholder():
    """GW-06: JWKS unavailable → gateway-stub uses pre-configured tokens; no JWKS validation."""
    pytest.skip("Gateway-stub uses static token registry, not JWKS")


def test_gw_07_placeholder():
    """GW-07: Scope-based /v1/ingest restriction not implemented in gateway-stub."""
    pytest.skip("Scope-based routing not implemented in gateway-stub")
