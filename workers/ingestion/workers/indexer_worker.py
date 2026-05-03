import logging

from elasticsearch import AsyncElasticsearch

from config import settings
from kafka_worker import KafkaWorker
from schemas import IngestionJob

logger = logging.getLogger(__name__)

_INDEX_BY_SENSITIVITY = {
    0: "public_index",
    1: "internal_index",
    2: "confidential_index",
    3: "restricted_index",
}


def _chunk_to_es_doc(chunk, job: IngestionJob, acl_tokens: list[str], acl_key: str) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "content": chunk.content,
        "source_uri": job.source_uri,
        "source_type": job.source_type,
        "sensitivity_level": job.sensitivity_level or 0,
        "acl_tokens": acl_tokens,
        "acl_key": acl_key,
        "page_number": chunk.page_number,
        "section": chunk.section,
        "vector": chunk.vector,
    }


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

        acl_tokens = job.acl_policy.acl_tokens if job.acl_policy else []
        acl_key = job.acl_policy.acl_key if job.acl_policy else ""

        bulk_body = []
        for chunk in job.chunks:
            if not chunk.chunk_id:
                logger.warning("Skipping chunk without chunk_id in job %s", job.job_id)
                continue
            bulk_body.append({"index": {"_index": target_index, "_id": chunk.chunk_id}})
            bulk_body.append(_chunk_to_es_doc(chunk, job, acl_tokens, acl_key))

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
