import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from unittest.mock import patch, MagicMock
import numpy as np

from schemas import RerankCandidate
from reranker import rerank, rerank_with_partial


def _mock_model(scores: list[float]):
    m = MagicMock()
    m.predict = MagicMock(return_value=np.array(scores))
    return m


def test_rnk_01_returns_sorted_candidates():
    candidates = [
        RerankCandidate(chunk_id="c1", content="first doc"),
        RerankCandidate(chunk_id="c2", content="second doc"),
        RerankCandidate(chunk_id="c3", content="third doc"),
    ]
    with patch("reranker._get_model", return_value=_mock_model([0.5, 0.9, 0.3])):
        results = rerank("query", candidates)
    assert results[0].chunk_id == "c2"
    assert results[0].rerank_score == pytest.approx(0.9)
    assert results[-1].chunk_id == "c3"


def test_rnk_05_empty_candidates():
    results = rerank("query", [])
    assert results == []


def test_rnk_07_response_has_no_content():
    candidates = [RerankCandidate(chunk_id="c1", content="sensitive content")]
    with patch("reranker._get_model", return_value=_mock_model([0.8])):
        results = rerank("query", candidates)
    assert len(results) == 1
    assert "content" not in results[0].model_dump()


def test_rnk_06_partial_failure_returns_scored_plus_unscored():
    """RNK-06: 1 of 3 candidates raises on per-item predict → partial=True; unscored listed."""
    call_count = {"n": 0}

    def side_effect_predict(pairs, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("batch failed")
        if pairs[0][1] == "bad content":
            raise RuntimeError("item failed")
        return np.array([0.7])

    model = MagicMock()
    model.predict = MagicMock(side_effect=side_effect_predict)

    candidates = [
        RerankCandidate(chunk_id="c1", content="good content"),
        RerankCandidate(chunk_id="c2", content="bad content"),
        RerankCandidate(chunk_id="c3", content="also good"),
    ]
    with patch("reranker._get_model", return_value=model):
        result = rerank_with_partial("query", candidates)

    assert result.partial is True
    assert "c2" in result.unscored_chunk_ids
    assert len(result.ranked) == 2
    assert all(r.chunk_id != "c2" for r in result.ranked)


def test_rnk_08_different_candidates_produce_different_scores():
    """RNK-08: Same query, different candidate content → different scores (model-based, not cached)."""
    model_a = _mock_model([0.9])
    model_b = _mock_model([0.2])

    candidates_a = [RerankCandidate(chunk_id="cA", content="highly relevant finance report")]
    candidates_b = [RerankCandidate(chunk_id="cB", content="unrelated HR onboarding doc")]

    with patch("reranker._get_model", return_value=model_a):
        results_a = rerank("What are the finance regulations?", candidates_a)
    with patch("reranker._get_model", return_value=model_b):
        results_b = rerank("What are the finance regulations?", candidates_b)

    assert results_a[0].rerank_score != results_b[0].rerank_score
