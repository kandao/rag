import os
import re
from typing import Literal

import yaml

TOPIC_VOCAB_PATH = os.environ.get("TOPIC_VOCAB_PATH", "/config/topic-vocabulary.yaml")

_TOPIC_VOCAB: dict[str, list[str]] = {}
_VOCAB_LOADED = False


def _load_vocab() -> None:
    global _TOPIC_VOCAB, _VOCAB_LOADED
    if _VOCAB_LOADED:
        return
    try:
        with open(TOPIC_VOCAB_PATH) as f:
            data = yaml.safe_load(f) or {}
        _TOPIC_VOCAB = data.get("topics", {})
    except FileNotFoundError:
        _TOPIC_VOCAB = {}
    _VOCAB_LOADED = True


_DOC_TYPE_PATTERNS = [
    ("regulation", re.compile(r"\bregulat(ion|ory)\b", re.I)),
    ("policy",     re.compile(r"\bpolic(y|ies)\b", re.I)),
    ("report",     re.compile(r"\breport\b", re.I)),
    ("memo",       re.compile(r"\bmemo\b", re.I)),
    ("guideline",  re.compile(r"\bguideline\b", re.I)),
]

_INTENT_RULES: list[tuple[Literal["comparison", "policy_lookup", "summary", "factual_lookup"], re.Pattern]] = [
    ("comparison",    re.compile(r"\b(compare|comparison|difference between|vs\.?)\b", re.I)),
    ("summary",       re.compile(r"\b(summarize|summarise|summary of|overview|what is)\b", re.I)),
    ("policy_lookup", re.compile(r"\b(regulation|policy|rule|procedure|standard|compliance)\b", re.I)),
]

_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
_QUARTER_PATTERN = re.compile(r"\bQ([1-4])\s*(20\d{2})\b", re.I)
_KEYWORD_STOPWORDS = {"the", "a", "an", "of", "in", "to", "is", "are", "for", "and", "or", "what", "how", "why"}


def extract_keywords(query: str) -> list[str]:
    tokens = re.findall(r"\b[A-Za-z0-9][\w\-]*\b", query)
    return [t for t in tokens if t.lower() not in _KEYWORD_STOPWORDS and len(t) > 2][:10]


def match_topic(query: str) -> str | None:
    # TEMPORARILY DISABLED: substring matching causes false positives (e.g. "api" in
    # "capital") which propagate into hard ES filters and return zero results.
    # Fix needed: switch to word-boundary regex matching + soft boost instead of hard filter.
    return None
    # _load_vocab()
    # q = query.lower()
    # for topic, keywords in _TOPIC_VOCAB.items():
    #     if topic == "default":
    #         continue
    #     for kw in keywords:
    #         if kw.lower() in q:
    #             return topic


def match_doc_type(query: str) -> str | None:
    for doc_type, pattern in _DOC_TYPE_PATTERNS:
        if pattern.search(query):
            return doc_type
    return None


def extract_time_range(query: str) -> dict | None:
    qm = _QUARTER_PATTERN.search(query)
    if qm:
        return {"year": int(qm.group(2))}
    ym = _YEAR_PATTERN.search(query)
    if ym:
        return {"year": int(ym.group(1))}
    return None


def classify_intent(query: str) -> Literal["comparison", "policy_lookup", "summary", "factual_lookup", "unknown"]:
    for intent, pattern in _INTENT_RULES:
        if pattern.search(query):
            return intent
    return "factual_lookup"


def parse(query: str) -> dict:
    """Return a dict of extracted QueryContext fields (without request_id or risk_signal)."""
    return {
        "raw_query": query,
        "keywords": extract_keywords(query),
        "topic": match_topic(query),
        "doc_type": match_doc_type(query),
        "time_range": extract_time_range(query),
        "intent": classify_intent(query),
    }
