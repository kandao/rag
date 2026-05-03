import pytest
from unittest.mock import AsyncMock

from rag_common.models.audit import AuditEvent
from internal.audit.emitter import emit, AuditFailClosedError
from internal.audit.es_writer import AuditWriteError


def _event() -> AuditEvent:
    return AuditEvent(
        event_id="evt-001", request_id="r1",
        timestamp="2024-01-01T00:00:00+00:00",
        user_id="u1", claims_digest="cd", acl_key="k", acl_version="v1",
        target_indexes=["confidential_index"],
        retrieved_chunk_ids=["c1"], ranked_chunk_ids=["c1"],
        sensitivity_levels_accessed=[2],
        model_path="private_l2", authorization_decision="allowed",
        query_risk_signal="none", answer_returned=True, latency_ms=300,
    )


@pytest.mark.asyncio
async def test_aud_05_l3_audit_timeout_raises_fail_closed():
    """AUD-05: L2/L3 audit write times out → AuditFailClosedError raised (fail-closed)."""
    es = AsyncMock()
    es.create = AsyncMock(side_effect=Exception("request timed out after 5s"))

    with pytest.raises(AuditFailClosedError) as exc:
        await emit(es_client=es, event=_event(), fail_closed=True)
    assert exc.value.code == "ERR_AUDIT_FAILED_CLOSED"


@pytest.mark.asyncio
async def test_l0l1_audit_write_failure_does_not_raise():
    """L0/L1 audit write failure is fire-and-forget; caller is never notified."""
    es = AsyncMock()
    es.create = AsyncMock(side_effect=Exception("ES unavailable"))

    await emit(es_client=es, event=_event(), fail_closed=False)
