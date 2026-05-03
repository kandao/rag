import hashlib


def compute_acl_key(
    sorted_tokens: list[str],
    token_schema_version: str,
    acl_version: str,
) -> str:
    """Compute acl_key = SHA-256(sorted_tokens | token_schema_version | acl_version).

    Tokens must be pre-sorted by the caller. The pipe-delimited join ensures
    uniqueness across token boundaries.
    """
    payload = "|".join(sorted_tokens) + "|" + token_schema_version + "|" + acl_version
    return hashlib.sha256(payload.encode()).hexdigest()
