import logging

from config import settings
from kafka_worker import KafkaWorker
from pipeline.chunk import chunk_job, split_into_chunks
from schemas import IngestionJob

logger = logging.getLogger(__name__)


class ChunkerWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_scanned,
            output_topic=settings.kafka_topic_chunked,
        )

    async def process(self, job: IngestionJob) -> IngestionJob:
        return chunk_job(
            job,
            chunk_size=settings.chunk_size_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
