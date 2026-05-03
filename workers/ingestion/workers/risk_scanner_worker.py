import logging
import re

from config import settings
from kafka_worker import KafkaWorker
from schemas import IngestionJob

logger = logging.getLogger(__name__)

_SENSITIVITY_RULES = [
    (3, [r"CONFIDENTIAL\s*[-–]\s*RESTRICTED", r"TOP SECRET", r"RESTRICTED ACCESS"]),
    (2, [r"CONFIDENTIAL", r"DO NOT DISTRIBUTE", r"INTERNAL ONLY\s*[-–]\s*CONFIDENTIAL"]),
    (1, [r"INTERNAL USE ONLY", r"NOT FOR PUBLIC RELEASE"]),
]

_INJECTION_SANITIZE = [
    re.compile(r"<\|im_start\|>system", re.IGNORECASE),
    re.compile(r"ignore previous instructions", re.IGNORECASE),
    re.compile(r"\[SYSTEM\]", re.IGNORECASE),
]

_INJECTION_QUARANTINE = [
    re.compile(r"OVERRIDE ALL SAFETY RULES", re.IGNORECASE),
]


def _detect_sensitivity(text: str) -> int:
    for level, patterns in _SENSITIVITY_RULES:
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return level
    return 0


def _needs_quarantine(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION_QUARANTINE)


def _sanitize(text: str) -> str:
    for pat in _INJECTION_SANITIZE:
        text = pat.sub("[FILTERED]", text)
    return text


class RiskScannerWorker(KafkaWorker):
    def __init__(self):
        super().__init__(
            input_topic=settings.kafka_topic_parsed,
            output_topic=settings.kafka_topic_scanned,
        )

    async def process(self, job: IngestionJob) -> IngestionJob | None:
        max_sensitivity = 0
        sanitized_sections = []

        for section in job.parsed_sections:
            if _needs_quarantine(section.content):
                logger.warning("Quarantining job %s: injection pattern detected", job.job_id)
                quarantine = job.model_copy(update={"stage": "quarantined"})
                await self.producer.send(
                    settings.kafka_topic_quarantine,
                    value=quarantine.model_dump_json().encode(),
                    key=job.source_uri.encode(),
                )
                return None

            level = _detect_sensitivity(section.content)
            max_sensitivity = max(max_sensitivity, level)
            sanitized_content = _sanitize(section.content)
            sanitized_sections.append(section.model_copy(update={"content": sanitized_content}))

        return job.model_copy(update={
            "parsed_sections": sanitized_sections,
            "sensitivity_level": max_sensitivity,
            "stage": "risk_scanner",
        })
