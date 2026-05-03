import os
import pytest

os.environ.setdefault("CLAIMS_SIGNING_KEY", "test-signing-key")

from tests.conftest import make_claims_headers, SIGNING_KEY
from internal.claims.normalizer import normalize_claims, ClaimsNormalizationError


def test_acl_norm_01_valid_claims():
    claims = {"user_id": "u1", "groups": ["a", "b", "c", "d", "e"], "role": None, "clearance_level": 1}
    hdr, sig = make_claims_headers(claims)
    result = normalize_claims(hdr, sig)
    assert result.user_id == "u1"
    assert len(result.groups) == 5


def test_acl_norm_02_dedup_groups():
    claims = {"user_id": "u1", "groups": ["eng:public", "eng:public", "eng:public"], "role": None, "clearance_level": 0}
    hdr, sig = make_claims_headers(claims)
    result = normalize_claims(hdr, sig)
    assert result.groups == ["eng:public"]


def test_acl_norm_03_invalid_hmac():
    claims = {"user_id": "u1", "groups": [], "clearance_level": 0}
    hdr, _ = make_claims_headers(claims)
    with pytest.raises(ClaimsNormalizationError) as exc:
        normalize_claims(hdr, "bad-sig")
    assert exc.value.code == "ERR_AUTH_UNTRUSTED_CLAIMS"


def test_acl_norm_04_missing_clearance():
    claims = {"user_id": "u1", "groups": []}
    hdr, sig = make_claims_headers(claims)
    with pytest.raises(ClaimsNormalizationError) as exc:
        normalize_claims(hdr, sig)
    assert exc.value.code == "ERR_AUTH_MISSING_CLAIMS"
