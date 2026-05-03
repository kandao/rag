import os
import re

import yaml

SYNONYM_CONFIG_PATH = os.environ.get("SYNONYM_CONFIG_PATH", "/config/synonym-config.yaml")
QUERY_EXPANSION_MAX_VARIANTS = int(os.environ.get("QUERY_EXPANSION_MAX_VARIANTS", "3"))

_SYNONYMS: dict[str, list[str]] = {}
_LOADED = False


def _load_synonyms() -> None:
    global _SYNONYMS, _LOADED
    if _LOADED:
        return
    try:
        with open(SYNONYM_CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}
        _SYNONYMS = data.get("synonyms", {})
    except FileNotFoundError:
        _SYNONYMS = {}
    _LOADED = True


def _get_synonyms(keyword: str) -> list[str]:
    _load_synonyms()
    return _SYNONYMS.get(keyword.lower(), [])


def expand(raw_query: str, context: dict, clearance_level: int) -> list[str]:
    """Produce up to QUERY_EXPANSION_MAX_VARIANTS rule-based query variants.

    LLM variants are deferred — callers that want them must inject them separately.
    """
    variants: list[str] = []
    intent = context.get("intent")
    keywords = context.get("keywords", [])
    doc_type = context.get("doc_type")

    if intent == "policy_lookup" and keywords:
        variants.append("regulations about " + " ".join(keywords[:3]))

    if doc_type and keywords:
        variants.append(f"{doc_type} regarding {' '.join(keywords[:3])}")

    for kw in keywords[:3]:
        syns = _get_synonyms(kw)
        if syns:
            variants.append(raw_query.replace(kw, syns[0], 1))
            break

    seen = set()
    result = []
    for v in variants:
        if v != raw_query and v not in seen:
            seen.add(v)
            result.append(v)
        if len(result) >= QUERY_EXPANSION_MAX_VARIANTS:
            break
    return result


def decompose_query(raw_query: str, intent: str) -> list[str]:
    """Split a comparison query into independent sub-queries. Returns [raw_query] for other intents."""
    if intent != "comparison":
        return [raw_query]

    match = re.search(r"\b(?:compare|difference between|vs\.?)\s+(.+?)\s+and\s+(.+?)(?:\s+regarding|\s*$)", raw_query, re.I)
    if match:
        a, b = match.group(1).strip(), match.group(2).strip()
        context_suffix = raw_query[match.end():].strip()
        suffix = f" regarding {context_suffix}" if context_suffix else ""
        return [f"Details about {a}{suffix}", f"Details about {b}{suffix}"]

    return [raw_query]
