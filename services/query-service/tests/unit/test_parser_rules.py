import os
os.environ.setdefault("TOPIC_VOCAB_PATH",
    os.path.join(os.path.dirname(__file__), "../../../../deploy/config/topic-vocabulary.yaml"))

import internal.guard.injection_detector as _inj
import internal.understanding.parser_rules as _mod
_mod._VOCAB_LOADED = False

from internal.understanding.parser_rules import (
    classify_intent, extract_keywords, extract_time_range, match_doc_type, match_topic, parse
)


def test_qu_01_medical_device():
    result = parse("What are the 2024 medical device regulation updates?")
    assert "regulation" in result["keywords"] or result["doc_type"] == "regulation"
    assert result["intent"] == "policy_lookup"
    assert result["time_range"] == {"year": 2024}


def test_qu_02_compare_intent():
    result = parse("Compare the old and new finance reporting procedures")
    assert result["intent"] == "comparison"
    assert result["topic"] == "finance"


def test_qu_03_time_range_and_finance():
    result = parse("Revenue figures for Q3 2023")
    assert result["time_range"] == {"year": 2023}
    assert result["topic"] == "finance"
    assert result["intent"] == "factual_lookup"


def test_qu_04_summary_hr():
    result = parse("Summarize company onboarding policy")
    assert result["intent"] == "summary"
    assert result["topic"] == "hr"
    assert result["doc_type"] == "policy"
