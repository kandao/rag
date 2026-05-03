import pytest


@pytest.fixture
def sample_texts():
    return [
        "The quarterly revenue exceeded expectations.",
        "四半期の収益は予想を上回りました。",
        "本季度收入超出预期。",
    ]
