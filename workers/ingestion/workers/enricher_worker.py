import logging

from config import settings
from kafka_worker import KafkaWorker
from pipeline.enrich import (
    classify_doc_type as _classify_doc_type,
    classify_topic as _classify_topic,
    enrich_job,
    extract_year as _extract_year,
    generate_doc_id as _generate_doc_id,
)
from schemas import IngestionJob

logger = logging.getLogger(__name__)


class EnricherWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_chunked,
            output_topic=settings.kafka_topic_enriched,
        )

    async def process(self, job: IngestionJob) -> IngestionJob:
        return enrich_job(job)
