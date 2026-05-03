from schemas import EmbedRequest, EmbedResponse


def test_embed_request_valid():
    req = EmbedRequest(texts=["hello", "world"])
    assert len(req.texts) == 2


def test_embed_response_valid():
    resp = EmbedResponse(vectors=[[0.1, 0.2], [0.3, 0.4]])
    assert len(resp.vectors) == 2
    assert len(resp.vectors[0]) == 2


def test_embed_request_empty():
    req = EmbedRequest(texts=[])
    assert req.texts == []
