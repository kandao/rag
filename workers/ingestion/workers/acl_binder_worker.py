import logging

from rag_common.acl.acl_key import compute_acl_key
from rag_common.acl.token_compression import compress_groups_to_tokens

from config import settings
from kafka_worker import KafkaWorker
from schemas import ACLPolicy, IngestionJob

logger = logging.getLogger(__name__)


def _normalize_role(role: str) -> str:
    return role.lower().replace(" ", "_")


class ACLBinderWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_enriched,
            output_topic=settings.kafka_topic_acl_bound,
        )

    async def process(self, job: IngestionJob) -> IngestionJob:
        acl_policy = job.acl_policy

        if acl_policy is None or (
            not acl_policy.allowed_groups and not acl_policy.allowed_roles
        ):
            logger.warning(
                "No ACL policy for %s — chunks will be invisible", job.source_uri
            )
            empty_acl_key = compute_acl_key(
                sorted_tokens=[],
                token_schema_version=settings.token_schema_version,
                acl_version=settings.acl_version,
            )
            bound_chunks = []
            for chunk in job.chunks:
                bound_chunks.append(chunk.model_copy(update={
                    # acl_tokens field not on Chunk; ACL stored at job level
                }))
            empty_policy = ACLPolicy(
                allowed_groups=[],
                allowed_roles=[],
                acl_tokens=[],
                acl_key=empty_acl_key,
                acl_version=settings.token_schema_version,
            )
            return job.model_copy(update={"acl_policy": empty_policy, "stage": "acl_binder"})

        group_tokens = compress_groups_to_tokens(acl_policy.allowed_groups)
        role_tokens = [f"role:{_normalize_role(r)}" for r in acl_policy.allowed_roles]
        acl_tokens = list(dict.fromkeys(group_tokens + role_tokens))  # deduplicate preserving order

        acl_key = compute_acl_key(
            sorted_tokens=sorted(acl_tokens),
            token_schema_version=settings.token_schema_version,
            acl_version=settings.acl_version,
        )

        bound_policy = ACLPolicy(
            allowed_groups=acl_policy.allowed_groups,
            allowed_roles=acl_policy.allowed_roles,
            acl_tokens=acl_tokens,
            acl_key=acl_key,
            acl_version=settings.token_schema_version,
        )

        # Stamp sensitivity_level onto each chunk
        bound_chunks = [
            chunk.model_copy(update={})
            for chunk in job.chunks
        ]

        return job.model_copy(update={
            "acl_policy": bound_policy,
            "chunks": bound_chunks,
            "stage": "acl_binder",
        })
