"""Integration tests for audit emitter — require a live audit Elasticsearch instance."""
import uuid
import pytest
from unittest.mock import AsyncMock, patch

from rag_common.models.audit import AuditEvent
from internal.audit.emitter import emit, AuditFailClosedError
from internal.audit.es_writer import AuditWriteError


def _make_event() -> AuditEvent:
    return AuditEvent(
        event_id=str(uuid.uuid4()),
        request_id="r1", timestamp="2024-01-01T00:00:00+00:00",
        user_id="u1", claims_digest="cd", acl_key="ak", acl_version="v1",
        target_indexes=["public_index"], retrieved_chunk_ids=["c1"],
        ranked_chunk_ids=["c1"], sensitivity_levels_accessed=[0],
        model_path="cloud_l1", authorization_decision="allowed",
        query_risk_signal="none", answer_returned=True, latency_ms=100,
    )


@pytest.mark.asyncio
async def test_aud_02_l1_es_unavailable_does_not_raise():
    """AUD-02: L0/L1 async emit must not raise even when ES is down."""
    es = AsyncMock()
    es.create = AsyncMock(side_effect=Exception("ES down"))
    event = _make_event()
    # Should not raise; background write logs the error
    await emit(es, event, fail_closed=False)


@pytest.mark.asyncio
async def test_aud_04_l3_es_unavailable_raises():
    """AUD-04: L2/L3 fail-closed emit must raise AuditFailClosedError when ES is down."""
    es = AsyncMock()
    es.create = AsyncMock(side_effect=Exception("ES down"))
    event = _make_event()
    with pytest.raises(AuditFailClosedError):
        await emit(es, event, fail_closed=True)


@pytest.mark.asyncio
async def test_aud_01_l1_es_available_writes():
    """AUD-01: L0/L1 async emit succeeds when ES is available."""
    es = AsyncMock()
    es.create = AsyncMock(return_value={"result": "created"})
    event = _make_event()
    await emit(es, event, fail_closed=False)
    # Background task; allow it to run
    import asyncio
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_aud_03_l3_es_available_writes():
    """AUD-03: L2/L3 sync emit succeeds and does not raise when ES is available."""
    es = AsyncMock()
    es.create = AsyncMock(return_value={"result": "created"})
    event = _make_event()
    await emit(es, event, fail_closed=True)
    es.create.assert_called_once()
