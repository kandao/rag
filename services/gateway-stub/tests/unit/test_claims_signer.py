import base64
import hashlib
import hmac
import json

from schemas import Claims
from claims_signer import sign_claims


def _make_claims(**kwargs) -> Claims:
    defaults = dict(user_id="user_l0", groups=["eng:public"], role=None, clearance_level=0)
    defaults.update(kwargs)
    return Claims(**defaults)


def test_sign_claims_returns_tuple():
    claims = _make_claims()
    b64, sig = sign_claims(claims, "test-key")
    assert isinstance(b64, str)
    assert isinstance(sig, str)


def test_sign_claims_b64_decodable():
    claims = _make_claims()
    b64, _ = sign_claims(claims, "test-key")
    decoded = base64.b64decode(b64)
    data = json.loads(decoded)
    assert data["user_id"] == "user_l0"
    assert data["clearance_level"] == 0


def test_sign_claims_hmac_verifiable():
    claims = _make_claims()
    signing_key = "secret-key"
    b64, sig = sign_claims(claims, signing_key)
    claims_json = base64.b64decode(b64).decode()
    expected_sig = hmac.new(signing_key.encode(), claims_json.encode(), hashlib.sha256).hexdigest()
    assert sig == expected_sig


def test_sign_claims_different_keys_different_sigs():
    claims = _make_claims()
    _, sig1 = sign_claims(claims, "key1")
    _, sig2 = sign_claims(claims, "key2")
    assert sig1 != sig2


def test_sign_claims_includes_iat():
    claims = _make_claims()
    b64, _ = sign_claims(claims, "key")
    data = json.loads(base64.b64decode(b64))
    assert "iat" in data
    assert data["iat"] > 0
