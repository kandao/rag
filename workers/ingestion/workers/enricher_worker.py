import hashlib
import logging
import re
from datetime import datetime, timezone

from config import settings
from kafka_worker import KafkaWorker
from schemas import IngestionJob

logger = logging.getLogger(__name__)

_TOPIC_KEYWORDS = {
    "finance": ["revenue", "profit", "budget", "fiscal", "earnings", "financial"],
    "engineering": ["deploy", "kubernetes", "api", "service", "infrastructure", "code"],
    "hr": ["employee", "policy", "benefits", "leave", "onboarding", "performance"],
    "legal": ["contract", "agreement", "compliance", "regulation", "liability"],
    "strategy": ["acquisition", "merger", "roadmap", "strategy", "initiative"],
}

_DOC_TYPE_KEYWORDS = {
    "report": ["report", "analysis", "summary", "review"],
    "policy": ["policy", "guideline", "procedure", "standard"],
    "memo": ["memo", "memorandum", "note"],
    "contract": ["contract", "agreement", "terms"],
    "minutes": ["minutes", "meeting"],
}


def _generate_doc_id(source_uri: str) -> str:
    return hashlib.sha256(source_uri.encode()).hexdigest()


def _classify_topic(content: str) -> str:
    lower = content.lower()
    for topic, keywords in _TOPIC_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return topic
    return "general"


def _classify_doc_type(content: str, metadata: dict) -> str:
    combined = (content + " " + str(metadata)).lower()
    for doc_type, keywords in _DOC_TYPE_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return doc_type
    return "document"


def _extract_year(content: str, metadata: dict) -> int | None:
    combined = content + " " + str(metadata)
    match = re.search(r"\b(20\d{2})\b", combined)
    if match:
        return int(match.group(1))
    return None


class EnricherWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_chunked,
            output_topic=settings.kafka_topic_enriched,
        )

    async def process(self, job: IngestionJob) -> IngestionJob:
        doc_id = _generate_doc_id(job.source_uri)
        now = datetime.now(timezone.utc).isoformat()

        enriched_chunks = []
        for i, chunk in enumerate(job.chunks):
            enriched_chunks.append(chunk.model_copy(update={
                "doc_id": doc_id,
                "chunk_id": f"{doc_id}-{i}",
            }))

        return job.model_copy(update={
            "chunks": enriched_chunks,
            "stage": "metadata_enricher",
            "updated_at": now,
        })
