import logging
import os

from elasticsearch import AsyncElasticsearch

from rag_common.models.audit import AuditEvent

logger = logging.getLogger(__name__)

AUDIT_ES_HOSTS = os.environ.get("AUDIT_ES_HOSTS", "https://audit-elasticsearch.retrieval-deps:9200")
AUDIT_INDEX_ALIAS = os.environ.get("AUDIT_INDEX_ALIAS", "audit-events-current")
AUDIT_WRITE_TIMEOUT_MS = int(os.environ.get("AUDIT_WRITE_TIMEOUT_MS", "5000"))


class AuditWriteError(Exception):
    pass


async def write_audit_event(es_client: AsyncElasticsearch, event: AuditEvent) -> None:
    """Write a single audit event to the audit index.

    Uses create (not index) to enforce append-only semantics — duplicate event_id is rejected.
    Raises AuditWriteError on failure.
    """
    try:
        await es_client.create(
            index=AUDIT_INDEX_ALIAS,
            id=event.event_id,
            document=event.model_dump(),
            request_timeout=AUDIT_WRITE_TIMEOUT_MS / 1000,
        )
    except Exception as exc:
        raise AuditWriteError(f"Audit write failed: {exc}") from exc
