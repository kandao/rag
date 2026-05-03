import pytest
from unittest.mock import MagicMock, patch
import numpy as np


def _make_mock_model(dims: int = 1024):
    model = MagicMock()
    model.tokenizer.encode.side_effect = lambda text: list(range(min(len(text), 100)))
    model.encode.side_effect = lambda texts, **kwargs: np.random.rand(len(texts), dims).astype("float32")
    return model


@pytest.fixture(autouse=True)
def reset_model():
    import embedder
    embedder._model = None
    yield
    embedder._model = None


def test_encode_english(sample_texts):
    with patch("embedder.load_model", return_value=_make_mock_model(1024)):
        from embedder import encode
        vectors = encode([sample_texts[0]])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024


def test_encode_japanese(sample_texts):
    with patch("embedder.load_model", return_value=_make_mock_model(1024)):
        from embedder import encode
        vectors = encode([sample_texts[1]])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024


def test_encode_chinese(sample_texts):
    with patch("embedder.load_model", return_value=_make_mock_model(1024)):
        from embedder import encode
        vectors = encode([sample_texts[2]])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024


def test_encode_exceeds_max_seq_len():
    model = _make_mock_model(1024)
    model.tokenizer.encode.side_effect = lambda text: list(range(9000))
    with patch("embedder.load_model", return_value=model):
        from embedder import encode
        with pytest.raises(ValueError, match="exceeds max sequence length"):
            encode(["x" * 10000])


def test_encode_batch_multiple():
    with patch("embedder.load_model", return_value=_make_mock_model(1024)):
        from embedder import encode
        texts = ["text one", "text two", "text three"]
        vectors = encode(texts)
    assert len(vectors) == 3
    assert all(len(v) == 1024 for v in vectors)
