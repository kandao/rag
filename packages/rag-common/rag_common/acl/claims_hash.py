import hashlib


def compute_claims_hash(
    groups: list[str],
    role: str | None,
    clearance_level: int,
    token_schema_version: str,
    acl_version: str,
) -> str:
    """Compute claims_hash = SHA-256(sorted_groups | role | clearance | versions).

    Used as the Redis auth-cache lookup key. Changing TOKEN_SCHEMA_VERSION or
    ACL_VERSION invalidates all existing cache entries (new hash, natural expiry).
    """
    sorted_groups = "|".join(sorted(groups))
    role_part = role or ""
    payload = (
        sorted_groups
        + "|" + role_part
        + "|" + str(clearance_level)
        + "|" + token_schema_version
        + "|" + acl_version
    )
    return hashlib.sha256(payload.encode()).hexdigest()
