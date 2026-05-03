import os
from dataclasses import dataclass

import yaml

from rag_common.models.query import QueryContext
from rag_common.models.user_context import UserContext

TOPIC_ROUTING_PATH = os.environ.get("TOPIC_ROUTING_PATH", "/config/topic-routing-config.yaml")

_TOPIC_AFFINITY: dict[str, str] = {}
_ROUTING_LOADED = False


def _load_routing() -> None:
    global _TOPIC_AFFINITY, _ROUTING_LOADED
    if _ROUTING_LOADED:
        return
    try:
        with open(TOPIC_ROUTING_PATH) as f:
            data = yaml.safe_load(f) or {}
        _TOPIC_AFFINITY = data.get("topic_index_affinity", {})
    except FileNotFoundError:
        _TOPIC_AFFINITY = {}
    _ROUTING_LOADED = True


_CLEARANCE_TO_INDEXES = [
    "public_index",
    "internal_index",
    "confidential_index",
    "restricted_index",
]

L0L1_INDEXES = {"public_index", "internal_index"}
L2L3_INDEXES = {"confidential_index", "restricted_index"}


@dataclass
class RoutingDecision:
    target_indexes: list[str]
    allow_knn: bool
    routing_reason: str


def route(context: QueryContext, user_context: UserContext) -> RoutingDecision:
    """Map QueryContext + UserContext to a RoutingDecision."""
    _load_routing()

    accessible = list(reversed(_CLEARANCE_TO_INDEXES[: user_context.effective_clearance + 1]))

    if context.topic:
        affinity = _TOPIC_AFFINITY.get(context.topic)
        if affinity:
            candidates = [affinity]
            if affinity in accessible:
                reason = f"topic={context.topic} → affinity index {affinity}"
            else:
                reason = f"topic={context.topic} → affinity index {affinity} [ACL filters may deny]"
        else:
            candidates = list(accessible)
            reason = f"topic={context.topic} has no affinity; searching all accessible"
    else:
        candidates = list(accessible)
        reason = "no topic detected; searching all accessible indexes"

    has_l0l1 = any(i in L0L1_INDEXES for i in candidates)
    has_l2l3 = any(i in L2L3_INDEXES for i in candidates)
    allow_knn = not (has_l0l1 and has_l2l3)

    if not allow_knn:
        reason += " [kNN disabled: cross-tier dimension mismatch]"

    return RoutingDecision(
        target_indexes=candidates,
        allow_knn=allow_knn,
        routing_reason=reason,
    )
