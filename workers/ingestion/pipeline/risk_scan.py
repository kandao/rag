import re
from dataclasses import dataclass

from schemas import IngestionJob

_SENSITIVITY_RULES = [
    (3, [r"CONFIDENTIAL\s*[-\u2013]\s*RESTRICTED", r"TOP SECRET", r"RESTRICTED ACCESS"]),
    (2, [r"CONFIDENTIAL", r"DO NOT DISTRIBUTE", r"INTERNAL ONLY\s*[-\u2013]\s*CONFIDENTIAL"]),
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


@dataclass(frozen=True)
class RiskScanResult:
    job: IngestionJob | None
    quarantined_job: IngestionJob | None = None


def detect_sensitivity(text: str) -> int:
    for level, patterns in _SENSITIVITY_RULES:
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return level
    return 0


def needs_quarantine(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION_QUARANTINE)


def sanitize(text: str) -> str:
    for pat in _INJECTION_SANITIZE:
        text = pat.sub("[FILTERED]", text)
    return text


def scan_job(job: IngestionJob) -> RiskScanResult:
    max_sensitivity = 0
    sanitized_sections = []

    for section in job.parsed_sections:
        if needs_quarantine(section.content):
            quarantine = job.model_copy(update={"stage": "quarantined"})
            return RiskScanResult(job=None, quarantined_job=quarantine)

        level = detect_sensitivity(section.content)
        max_sensitivity = max(max_sensitivity, level)
        sanitized_sections.append(
            section.model_copy(update={"content": sanitize(section.content)})
        )

    scanned = job.model_copy(
        update={
            "parsed_sections": sanitized_sections,
            "sensitivity_level": max_sensitivity,
            "stage": "risk_scanner",
        }
    )
    return RiskScanResult(job=scanned)
