import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass


@dataclass
class NormalizedClaims:
    user_id: str
    groups: list[str]          # deduplicated and sorted
    role: str | None
    clearance_level: int


class ClaimsNormalizationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def normalize_claims(header_value: str, sig_header: str) -> NormalizedClaims:
    """Parse and verify X-Trusted-Claims + X-Claims-Sig.

    Raises ClaimsNormalizationError with ERR_AUTH_* codes on any failure.
    """
    signing_key = os.environ.get("CLAIMS_SIGNING_KEY", "")

    try:
        claims_json = base64.b64decode(header_value)
    except Exception:
        raise ClaimsNormalizationError("ERR_AUTH_MISSING_CLAIMS", "Invalid base64 in claims header")

    expected_sig = hmac.new(
        signing_key.encode(),
        claims_json,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, sig_header):
        raise ClaimsNormalizationError("ERR_AUTH_UNTRUSTED_CLAIMS", "HMAC signature mismatch")

    try:
        raw = json.loads(claims_json)
    except json.JSONDecodeError:
        raise ClaimsNormalizationError("ERR_AUTH_MISSING_CLAIMS", "Invalid JSON in claims")

    for field in ("user_id", "groups", "clearance_level"):
        if field not in raw:
            raise ClaimsNormalizationError("ERR_AUTH_MISSING_CLAIMS", f"Missing required field: {field}")

    clearance = raw["clearance_level"]
    if clearance not in (0, 1, 2, 3):
        raise ClaimsNormalizationError("ERR_AUTH_MISSING_CLAIMS", "clearance_level must be 0–3")

    groups = sorted(set(raw["groups"]))

    return NormalizedClaims(
        user_id=raw["user_id"],
        groups=groups,
        role=raw.get("role"),
        clearance_level=clearance,
    )
