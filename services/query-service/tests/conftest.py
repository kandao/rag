import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest

from rag_common.models.user_context import UserContext


SIGNING_KEY = "test-signing-key"


def make_claims_headers(claims: dict, key: str = SIGNING_KEY) -> tuple[str, str]:
    """Produce (X-Trusted-Claims, X-Claims-Sig) for a given claims dict."""
    claims_json = json.dumps(claims).encode()
    header_value = base64.b64encode(claims_json).decode()
    sig = hmac.new(key.encode(), claims_json, hashlib.sha256).hexdigest()
    return header_value, sig


@pytest.fixture
def sample_claims() -> dict:
    return {
        "user_id": "user_l1",
        "groups": ["eng:engineering", "eng:public"],
        "role": None,
        "clearance_level": 1,
    }


@pytest.fixture
def sample_user_context() -> UserContext:
    return UserContext(
        user_id="user_l1",
        effective_groups=["group:eng:engineering", "group:eng:public"],
        effective_clearance=1,
        acl_tokens=["group:eng:engineering", "group:eng:public", "level:1"],
        acl_key="abc123",
        token_schema_version="v1",
        acl_version="v1",
        claims_hash="def456",
        derived_at="2024-01-01T00:00:00+00:00",
    )


@pytest.fixture
def mock_redis():
    client = AsyncMock()
    client.get = AsyncMock(return_value=None)
    client.set = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_es():
    return AsyncMock()
