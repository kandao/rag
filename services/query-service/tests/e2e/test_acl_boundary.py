"""
HLD-ACL-04, HLD-ACL-05, HLD-ACL-08: ACL Boundary + Cross-User Isolation (Integration)

Requires: real Elasticsearch seeded with boundary chunks. No LLM.
Run with: pytest -m e2e tests/e2e/test_acl_boundary.py
"""
import pytest

from .conftest import query_via_gateway, get_chunk_ids, TOKENS

pytestmark = pytest.mark.e2e

# Chunk IDs seeded in ES at exactly sensitivity_level=2 (confidential boundary)
L2_BOUNDARY_CHUNK_IDS = {"legal-contract-q1-001", "m-and-a-memo-2024-001"}

# Queries that target L2 boundary content
L2_BOUNDARY_QUERY = "legal contracts confidential merger acquisition"

# Queries that target L1-only content visible to user_l1_a but not user_l1_b
L1_A_ONLY_CHUNK_IDS = {"eng-guide-2024-001"}   # visible to eng:engineering
L1_B_QUERY = "engineering guidelines software standards"


# ---------------------------------------------------------------------------
# HLD-ACL-04: Boundary chunk accessible when clearance == sensitivity
# ---------------------------------------------------------------------------

def test_hld_acl_04_boundary_chunk_accessible_at_exact_clearance(http):
    """L2 user (clearance=2) can see sensitivity=2 chunks (boundary must be inclusive)."""
    resp = query_via_gateway(http, "l2", L2_BOUNDARY_QUERY)
    assert resp.status_code == 200

    chunk_ids = set(get_chunk_ids(resp.json()))
    found_boundary = chunk_ids & L2_BOUNDARY_CHUNK_IDS

    assert found_boundary, (
        f"HLD-ACL-04: L2 user should see L2 boundary chunks {L2_BOUNDARY_CHUNK_IDS}, "
        f"but got: {chunk_ids}"
    )


# ---------------------------------------------------------------------------
# HLD-ACL-05: Boundary chunk inaccessible when clearance < sensitivity
# ---------------------------------------------------------------------------

def test_hld_acl_05_boundary_chunk_inaccessible_below_clearance(http):
    """L1 user (clearance=1) must NOT see sensitivity=2 chunks."""
    resp = query_via_gateway(http, "l1", L2_BOUNDARY_QUERY)
    assert resp.status_code == 200

    chunk_ids = set(get_chunk_ids(resp.json()))
    leaked = chunk_ids & L2_BOUNDARY_CHUNK_IDS

    assert not leaked, (
        f"HLD-ACL-05: L1 user (clearance=1) should not see L2 chunks, "
        f"but received: {leaked}"
    )


# ---------------------------------------------------------------------------
# HLD-ACL-08: Cross-user isolation — two L1 users with different group access see different results
# ---------------------------------------------------------------------------

def test_hld_acl_08_cross_user_isolation(http):
    """
    user_l1 (groups: eng:engineering, eng:public) and user_l1_b (groups: eng:public only)
    query the same string — user_l1 sees engineering chunks, user_l1_b does not.
    """
    # user_l1: has eng:engineering access → should see engineering-specific chunks
    resp_a = query_via_gateway(http, "l1", L1_B_QUERY)
    assert resp_a.status_code == 200
    chunk_ids_a = set(get_chunk_ids(resp_a.json()))

    # user_l1_b: public-only access → should NOT see eng:engineering chunks
    resp_b = query_via_gateway(http, "l1_b", L1_B_QUERY)
    assert resp_b.status_code == 200
    chunk_ids_b = set(get_chunk_ids(resp_b.json()))

    # The two result sets must differ
    assert chunk_ids_a != chunk_ids_b, (
        "HLD-ACL-08: user_l1 and user_l1_b returned identical results — "
        "cross-user isolation not enforced"
    )

    # Engineering chunks visible to l1 must NOT be visible to l1_b
    eng_in_b = chunk_ids_b & L1_A_ONLY_CHUNK_IDS
    assert not eng_in_b, (
        f"HLD-ACL-08: user_l1_b received engineering-restricted chunks: {eng_in_b}"
    )
