import pytest
from schemas import RerankCandidate


@pytest.fixture
def sample_candidates() -> list[RerankCandidate]:
    return [
        RerankCandidate(chunk_id=f"chunk-{i}", content=f"Content about topic {i}")
        for i in range(5)
    ]
