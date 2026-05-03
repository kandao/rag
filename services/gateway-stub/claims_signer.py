import base64
import hashlib
import hmac
import json
import time

from schemas import Claims


def sign_claims(claims: Claims, signing_key: str) -> tuple[str, str]:
    claims_dict = claims.model_dump()
    claims_dict["iat"] = int(time.time())
    claims_json = json.dumps(claims_dict, separators=(",", ":"), sort_keys=True)
    claims_b64 = base64.b64encode(claims_json.encode()).decode()
    sig = hmac.new(signing_key.encode(), claims_json.encode(), hashlib.sha256).hexdigest()
    return claims_b64, sig
