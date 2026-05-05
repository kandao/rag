import logging

from config import settings
from kafka_worker import KafkaWorker
from pipeline.acl_bind import bind_acl_job, normalize_role as _normalize_role
from schemas import IngestionJob

logger = logging.getLogger(__name__)


class ACLBinderWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_enriched,
            output_topic=settings.kafka_topic_acl_bound,
        )

    async def process(self, job: IngestionJob) -> IngestionJob:
        if job.acl_policy is None or (
            not job.acl_policy.allowed_groups and not job.acl_policy.allowed_roles
        ):
            logger.warning("No ACL policy for %s; chunks will be invisible", job.source_uri)
        return bind_acl_job(job)
