import os
import tempfile
import pytest
import yaml

os.environ.setdefault("TOKEN_SCHEMA_VERSION", "v1")
os.environ.setdefault("ACL_VERSION", "v1")

from internal.claims.normalizer import NormalizedClaims
from internal.claims.acl_adapter import derive_user_context


def test_derive_produces_user_context():
    nc = NormalizedClaims(user_id="u1", groups=["eng:infra@company.com"], role="manager", clearance_level=2)
    ctx = derive_user_context(nc)
    assert ctx.user_id == "u1"
    assert "group:eng:infra" in ctx.acl_tokens
    assert "role:manager" in ctx.acl_tokens
    assert "level:2" in ctx.acl_tokens
    assert ctx.effective_clearance == 2


def test_acl_norm_09_deterministic_acl_key():
    nc1 = NormalizedClaims(user_id="u1", groups=["eng:public", "eng:infra"], role=None, clearance_level=1)
    nc2 = NormalizedClaims(user_id="u1", groups=["eng:infra", "eng:public"], role=None, clearance_level=1)
    assert derive_user_context(nc1).acl_key == derive_user_context(nc2).acl_key


def test_acl_norm_07_hierarchy_compresses_to_accepted():
    """ACL-NORM-07: 32 raw tokens → hierarchy removes 4 children → 28 tokens ≤ 30 → accepted."""
    import internal.claims.acl_adapter as adapter

    # Flat hierarchy: child → parent (no 'hierarchy:' wrapper — that's what _apply_hierarchy_compression expects)
    flat_hierarchy = {
        "eng:infra-prod": "eng:infra",
        "eng:infra-staging": "eng:infra",
        "eng:eng-backend": "eng:engineering",
        "eng:eng-frontend": "eng:engineering",
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
        yaml.dump(flat_hierarchy, tf)
        tmppath = tf.name

    # 25 unique groups + 2 parents + 4 children = 31 groups
    # → 31 group tokens + 1 level = 32 raw tokens > 30 → triggers compression
    # → hierarchy removes 4 children → 27 group tokens + 1 level = 28 ≤ 30
    unique = [f"dept-{i:02d}@company.com" for i in range(25)]
    hierarchy_groups = [
        "eng:infra@company.com",
        "eng:infra-prod@company.com",
        "eng:infra-staging@company.com",
        "eng:engineering@company.com",
        "eng:eng-backend@company.com",
        "eng:eng-frontend@company.com",
    ]
    all_groups = unique + hierarchy_groups

    original_path = adapter.HIERARCHY_CONFIG_PATH
    adapter.HIERARCHY_CONFIG_PATH = tmppath
    try:
        nc = NormalizedClaims(user_id="u1", groups=all_groups, role=None, clearance_level=1)
        ctx = derive_user_context(nc)
        assert len(ctx.acl_tokens) <= 30
        assert ctx.effective_clearance == 1
    finally:
        adapter.HIERARCHY_CONFIG_PATH = original_path
        os.unlink(tmppath)


def test_token_count_exceeds_limit_raises():
    many_groups = [f"group{i}@company.com" for i in range(35)]
    nc = NormalizedClaims(user_id="u1", groups=many_groups, role=None, clearance_level=0)
    from internal.claims.acl_adapter import ACL_TOKEN_MAX_COUNT
    import internal.claims.acl_adapter as adapter
    original = adapter.ACL_TOKEN_MAX_COUNT
    adapter.ACL_TOKEN_MAX_COUNT = 5
    try:
        from internal.claims.normalizer import ClaimsNormalizationError
        with pytest.raises(ClaimsNormalizationError) as exc:
            derive_user_context(nc)
        assert exc.value.code == "ERR_AUTH_CLEARANCE_INSUFFICIENT"
    finally:
        adapter.ACL_TOKEN_MAX_COUNT = original
