import hashlib
import uuid
from datetime import datetime, timezone
from typing import Literal

from rag_common.models.audit import AuditEvent
from rag_common.models.retrieval import RankedCandidate, RetrievalCandidate
from rag_common.models.user_context import UserContext

AUDIT_FAIL_CLOSED_MIN_CLEARANCE = int(__import__("os").environ.get("AUDIT_FAIL_CLOSED_MIN_CLEARANCE", "2"))

QUERY_FRAGMENT_MAX_LEN = 100


def truncate_query_fragment(query: str) -> str:
    """AUD-06: truncate a query for inclusion in guard-block audit/log events."""
    return query[:QUERY_FRAGMENT_MAX_LEN]


def build_query_event(
    request_id: str,
    user_context: UserContext,
    target_indexes: list[str],
    retrieved: list[RetrievalCandidate],
    ranked: list[RankedCandidate],
    model_path: str,
    authorization_decision: Literal["allowed", "denied", "fail_closed"],
    query_risk_signal: str,
    answer_returned: bool,
    latency_ms: int,
) -> AuditEvent:
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        request_id=request_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        user_id=user_context.user_id,
        claims_digest=user_context.claims_hash,
        acl_key=user_context.acl_key,
        acl_version=user_context.acl_version,
        target_indexes=target_indexes,
        retrieved_chunk_ids=[c.chunk_id for c in retrieved],
        ranked_chunk_ids=[c.chunk_id for c in ranked],
        sensitivity_levels_accessed=sorted({c.sensitivity_level for c in retrieved}),
        model_path=model_path,
        authorization_decision=authorization_decision,
        query_risk_signal=query_risk_signal,
        answer_returned=answer_returned,
        latency_ms=latency_ms,
    )


def should_gate_on_audit(user_context: UserContext) -> bool:
    """Return True if this request requires fail-closed audit behavior (L2/L3)."""
    return user_context.effective_clearance >= AUDIT_FAIL_CLOSED_MIN_CLEARANCE
