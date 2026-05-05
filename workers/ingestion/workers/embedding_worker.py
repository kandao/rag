import logging

import httpx

from config import settings
from kafka_worker import KafkaWorker
from pipeline.embed import (
    auth_headers as _auth_headers,
    embed_job,
    embed_openai as _embed_openai,
    embed_private as _embed_private,
)
from schemas import IngestionJob

logger = logging.getLogger(__name__)


class EmbeddingWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_acl_bound,
            output_topic=settings.kafka_topic_embedded,
        )
        self._http: httpx.AsyncClient | None = None

    async def run(self):
        async with httpx.AsyncClient() as http:
            self._http = http
            await super().run()

    async def process(self, job: IngestionJob) -> IngestionJob:
        return await embed_job(job, http_client=self._http)
