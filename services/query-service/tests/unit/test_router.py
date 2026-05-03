import os
os.environ.setdefault("TOPIC_ROUTING_PATH",
    os.path.join(os.path.dirname(__file__), "../../../../deploy/config/topic-routing-config.yaml"))

import internal.routing.router as _mod
_mod._ROUTING_LOADED = False

from rag_common.models.query import QueryContext
from rag_common.models.user_context import UserContext
from internal.routing.router import route


def _ctx(clearance: int) -> UserContext:
    return UserContext(
        user_id="u1", effective_groups=[], effective_clearance=clearance,
        acl_tokens=[], acl_key="k", token_schema_version="v1", acl_version="v1",
        claims_hash="h", derived_at="2024-01-01T00:00:00+00:00",
    )


def _qctx(topic=None) -> QueryContext:
    return QueryContext(
        request_id="r1", raw_query="q", keywords=[], topic=topic,
        doc_type=None, time_range=None, intent="factual_lookup",
        risk_signal="none", expanded_queries=[],
    )


def test_qu_07_l1_finance_routes_internal():
    decision = route(_qctx("finance"), _ctx(1))
    assert decision.target_indexes == ["internal_index"]
    assert decision.allow_knn is True


def test_qu_08_l3_no_topic_all_indexes_no_knn():
    decision = route(_qctx(None), _ctx(3))
    assert set(decision.target_indexes) == {
        "public_index", "internal_index", "confidential_index", "restricted_index"
    }
    assert decision.allow_knn is False


def test_qu_09_l2_no_topic_knn_false():
    decision = route(_qctx(None), _ctx(2))
    assert "confidential_index" in decision.target_indexes
    assert "restricted_index" not in decision.target_indexes
    assert decision.allow_knn is False


def test_l1_no_topic_both_l0l1_knn_true():
    decision = route(_qctx(None), _ctx(1))
    assert decision.allow_knn is True
    assert "confidential_index" not in decision.target_indexes


def test_inaccessible_topic_affinity_routes_to_affinity_for_acl_filtering():
    decision = route(_qctx("legal"), _ctx(0))
    assert decision.target_indexes == ["confidential_index"]
    assert decision.allow_knn is True
    assert "ACL filters may deny" in decision.routing_reason
