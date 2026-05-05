import logging

from elasticsearch import AsyncElasticsearch

from config import settings
from kafka_worker import KafkaWorker
from pipeline.index import (
    INDEX_BY_SENSITIVITY as _INDEX_BY_SENSITIVITY,
    build_bulk_operations,
    chunk_to_es_doc as _chunk_to_es_doc,
)
from schemas import IngestionJob

logger = logging.getLogger(__name__)


class IndexerWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_embedded,
            output_topic="__sink__",
        )
        self._es: AsyncElasticsearch | None = None

    async def run(self):
        self._es = AsyncElasticsearch(
            hosts=settings.es_hosts.split(","),
            http_auth=(settings.es_username, settings.es_password) if settings.es_username else None,
        )
        try:
            await super().run()
        finally:
            await self._es.close()

    async def process(self, job: IngestionJob) -> IngestionJob | None:
        sensitivity = job.sensitivity_level or 0
        target_index = _INDEX_BY_SENSITIVITY.get(sensitivity, "public_index")
        bulk_body = build_bulk_operations(job)

        if not bulk_body:
            logger.warning("No chunks to index for job %s", job.job_id)
            return None

        result = await self._es.bulk(operations=bulk_body)
        if result.get("errors"):
            failed = [
                item for item in result["items"]
                if item.get("index", {}).get("error")
            ]
            logger.error("Bulk indexing errors for job %s: %d failed", job.job_id, len(failed))
            raise RuntimeError(f"Bulk indexing errors: {failed[:3]}")

        logger.info(
            "Indexed %d chunks for job %s → %s",
            len(job.chunks), job.job_id, target_index,
        )
        return job.model_copy(update={"stage": "complete"})
