import logging

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from config import settings
from schemas import IngestionJob

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class KafkaWorker:
    def __init__(self, input_topic: str, output_topic: str):
        self.input_topic = input_topic
        self.output_topic = output_topic
        self.consumer = AIOKafkaConsumer(
            input_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        self.producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers
        )

    async def run(self):
        async with self.consumer, self.producer:
            async for msg in self.consumer:
                job = IngestionJob.model_validate_json(msg.value)
                headers = dict(msg.headers)
                retry_count = int(headers.get("retry_count", b"0"))
                try:
                    result = await self.process(job)
                    if result is not None:
                        await self.producer.send(
                            self.output_topic,
                            value=result.model_dump_json().encode(),
                            key=job.source_uri.encode(),
                        )
                    await self.consumer.commit()
                except Exception as exc:
                    logger.error(
                        "Worker error on %s retry=%d: %s",
                        self.input_topic, retry_count, exc,
                    )
                    target = settings.kafka_topic_dlq if retry_count >= MAX_RETRIES else self.input_topic
                    await self.producer.send(
                        target,
                        value=msg.value,
                        headers=[
                            ("retry_count", str(retry_count + 1).encode()),
                            ("failed_stage", self.input_topic.encode()),
                            ("error", str(exc).encode()),
                        ],
                        key=job.source_uri.encode(),
                    )
                    await self.consumer.commit()

    async def process(self, job: IngestionJob) -> IngestionJob | None:
        raise NotImplementedError
