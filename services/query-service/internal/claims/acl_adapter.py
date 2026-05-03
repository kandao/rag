import os
from datetime import datetime, timezone

import yaml

from rag_common.acl.acl_key import compute_acl_key
from rag_common.acl.claims_hash import compute_claims_hash
from rag_common.acl.token_compression import compress_groups_to_tokens
from rag_common.models.user_context import UserContext

from .normalizer import ClaimsNormalizationError, NormalizedClaims

TOKEN_SCHEMA_VERSION = os.environ.get("TOKEN_SCHEMA_VERSION", "v1")
ACL_VERSION = os.environ.get("ACL_VERSION", "v1")
ACL_TOKEN_MAX_COUNT = int(os.environ.get("ACL_TOKEN_MAX_COUNT", "30"))
HIERARCHY_CONFIG_PATH = os.environ.get("HIERARCHY_CONFIG_PATH", "/config/acl-hierarchy-config.yaml")


def _normalize_role(role: str) -> str:
    return role.lower().replace(" ", "-")


def _apply_hierarchy_compression(tokens: list[str]) -> list[str]:
    try:
        with open(HIERARCHY_CONFIG_PATH) as f:
            hierarchy: dict = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return tokens

    result = set(tokens)
    for child, parent in hierarchy.items():
        child_tok = f"group:{child}"
        parent_tok = f"group:{parent}"
        if child_tok in result and parent_tok in result:
            result.discard(child_tok)

    return list(result)


def derive_user_context(normalized: NormalizedClaims) -> UserContext:
    """Convert NormalizedClaims into a full UserContext with acl_tokens and acl_key."""
    ch = compute_claims_hash(
        groups=normalized.groups,
        role=normalized.role,
        clearance_level=normalized.clearance_level,
        token_schema_version=TOKEN_SCHEMA_VERSION,
        acl_version=ACL_VERSION,
    )

    raw_tokens: list[str] = compress_groups_to_tokens(normalized.groups)

    if normalized.role is not None:
        raw_tokens.append("role:" + _normalize_role(normalized.role))

    for lvl in range(normalized.clearance_level + 1):
        raw_tokens.append("level:" + str(lvl))
    raw_tokens = list(dict.fromkeys(raw_tokens))  # deduplicate preserving order

    if len(raw_tokens) > ACL_TOKEN_MAX_COUNT:
        raw_tokens = _apply_hierarchy_compression(raw_tokens)
        if len(raw_tokens) > ACL_TOKEN_MAX_COUNT:
            raise ClaimsNormalizationError(
                "ERR_AUTH_CLEARANCE_INSUFFICIENT",
                f"ACL token count {len(raw_tokens)} exceeds limit {ACL_TOKEN_MAX_COUNT} after compression",
            )

    sorted_tokens = sorted(raw_tokens)
    acl_key = compute_acl_key(sorted_tokens, TOKEN_SCHEMA_VERSION, ACL_VERSION)

    return UserContext(
        user_id=normalized.user_id,
        effective_groups=[t for t in sorted_tokens if t.startswith("group:")],
        effective_clearance=normalized.clearance_level,
        acl_tokens=sorted_tokens,
        acl_key=acl_key,
        token_schema_version=TOKEN_SCHEMA_VERSION,
        acl_version=ACL_VERSION,
        claims_hash=ch,
        derived_at=datetime.now(timezone.utc).isoformat(),
    )
