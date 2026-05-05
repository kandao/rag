import logging

from config import settings
from kafka_worker import KafkaWorker
from pipeline.risk_scan import (
    detect_sensitivity as _detect_sensitivity,
    needs_quarantine as _needs_quarantine,
    sanitize as _sanitize,
    scan_job,
)
from schemas import IngestionJob

logger = logging.getLogger(__name__)


class RiskScannerWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_parsed,
            output_topic=settings.kafka_topic_scanned,
        )

    async def process(self, job: IngestionJob) -> IngestionJob | None:
        result = scan_job(job)
        if result.quarantined_job is not None:
            logger.warning("Quarantining job %s: injection pattern detected", job.job_id)
            await self.producer.send(
                settings.kafka_topic_quarantine,
                value=result.quarantined_job.model_dump_json().encode(),
                key=job.source_uri.encode(),
            )
            return None

        return result.job
