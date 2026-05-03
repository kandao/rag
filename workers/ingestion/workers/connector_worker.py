import logging
import uuid
from datetime import datetime, timezone

import httpx

from config import settings
from kafka_worker import KafkaWorker
from schemas import IngestionJob

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConnectorWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic="__trigger__",
            output_topic=settings.kafka_topic_raw,
        )

    async def ingest_url(self, source_uri: str, source_type: str, metadata: dict) -> IngestionJob:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(source_uri)
            resp.raise_for_status()

        if source_type == "pdf":
            return IngestionJob(
                job_id=str(uuid.uuid4()),
                source_type="pdf",
                source_uri=source_uri,
                source_metadata=metadata,
                raw_content_bytes=resp.content,
                stage="connector",
                created_at=_now(),
                updated_at=_now(),
            )
        else:
            return IngestionJob(
                job_id=str(uuid.uuid4()),
                source_type=source_type,
                source_uri=source_uri,
                source_metadata=metadata,
                raw_content=resp.text,
                stage="connector",
                created_at=_now(),
                updated_at=_now(),
            )

    async def ingest_file(self, path: str, source_type: str, metadata: dict) -> IngestionJob:
        if source_type == "pdf":
            with open(path, "rb") as f:
                raw_bytes = f.read()
            return IngestionJob(
                job_id=str(uuid.uuid4()),
                source_type="pdf",
                source_uri=path,
                source_metadata=metadata,
                raw_content_bytes=raw_bytes,
                stage="connector",
                created_at=_now(),
                updated_at=_now(),
            )
        else:
            with open(path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            return IngestionJob(
                job_id=str(uuid.uuid4()),
                source_type=source_type,
                source_uri=path,
                source_metadata=metadata,
                raw_content=raw_text,
                stage="connector",
                created_at=_now(),
                updated_at=_now(),
            )

    async def process(self, job: IngestionJob) -> IngestionJob:
        return job
