import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from schemas import RerankRequest, RerankResponse, RerankCandidate, RankedItem


def test_rerank_request_valid():
    req = RerankRequest(
        request_id="req-1",
        query="test query",
        candidates=[RerankCandidate(chunk_id="c1", content="content")],
    )
    assert req.request_id == "req-1"
    assert len(req.candidates) == 1


def test_rerank_response_no_content():
    resp = RerankResponse(
        request_id="req-1",
        ranked=[RankedItem(chunk_id="c1", rerank_score=0.9)],
    )
    assert resp.ranked[0].rerank_score == 0.9
    assert not hasattr(resp.ranked[0], "content")
