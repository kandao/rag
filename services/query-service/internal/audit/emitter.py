import asyncio
import logging

from elasticsearch import AsyncElasticsearch

from rag_common.models.audit import AuditEvent

from .es_writer import AuditWriteError, write_audit_event

logger = logging.getLogger(__name__)

AUDIT_WRITE_ERROR_CODE = "ERR_AUDIT_FAILED_CLOSED"


class AuditFailClosedError(Exception):
    code = AUDIT_WRITE_ERROR_CODE


async def emit(
    es_client: AsyncElasticsearch,
    event: AuditEvent,
    fail_closed: bool,
) -> None:
    """Emit an audit event.

    If fail_closed=True (L2/L3): write synchronously; raise AuditFailClosedError on failure.
    If fail_closed=False (L0/L1): fire-and-forget; log error but never raise.
    """
    if fail_closed:
        try:
            await write_audit_event(es_client, event)
        except AuditWriteError as exc:
            logger.error(
                "AUDIT WRITE FAILED — fail-closed",
                extra={"request_id": event.request_id, "error": str(exc)},
            )
            raise AuditFailClosedError("Audit write failed; response withheld (L2/L3)") from exc
    else:
        asyncio.ensure_future(_background_write(es_client, event))


async def _background_write(es_client: AsyncElasticsearch, event: AuditEvent) -> None:
    try:
        await write_audit_event(es_client, event)
    except AuditWriteError as exc:
        logger.error(
            "Audit write failed (non-critical, L0/L1)",
            extra={"request_id": event.request_id, "error": str(exc)},
        )
