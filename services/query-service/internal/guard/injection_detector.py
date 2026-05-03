import os
import re
from dataclasses import dataclass
from typing import Literal

import yaml

PATTERNS_PATH = os.environ.get("GUARD_INJECTION_PATTERNS_PATH", "/config/injection-patterns.yaml")

_HIGH_PATTERNS: list[tuple[str, re.Pattern]] = []
_MEDIUM_PATTERNS: list[tuple[str, re.Pattern]] = []
_LOADED = False


def _load_patterns() -> None:
    global _LOADED, _HIGH_PATTERNS, _MEDIUM_PATTERNS
    if _LOADED:
        return
    try:
        with open(PATTERNS_PATH) as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        config = {}

    for entry in config.get("injection_patterns", []):
        pid = entry["id"]
        risk = entry.get("risk", "MEDIUM").upper()
        compiled = [re.compile(p, re.IGNORECASE) for p in entry.get("patterns", [])]
        for regex in compiled:
            if risk == "HIGH":
                _HIGH_PATTERNS.append((pid, regex))
            else:
                _MEDIUM_PATTERNS.append((pid, regex))
    _LOADED = True


@dataclass
class InjectionResult:
    risk_level: Literal["none", "medium", "high"]
    pattern_id: str | None


def detect_injection(query: str) -> InjectionResult:
    """Check query against loaded injection patterns. Returns risk level and matching pattern ID."""
    _load_patterns()
    q = query.lower()

    for pid, regex in _HIGH_PATTERNS:
        if regex.search(q):
            return InjectionResult(risk_level="high", pattern_id=pid)

    for pid, regex in _MEDIUM_PATTERNS:
        if regex.search(q):
            return InjectionResult(risk_level="medium", pattern_id=pid)

    return InjectionResult(risk_level="none", pattern_id=None)
