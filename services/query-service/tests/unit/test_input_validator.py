import pytest

from internal.input_validator import (
    MAX_QUERY_LENGTH,
    InputValidationError,
    validate_query_length,
)


def test_guard_10_1000_chars_accepted():
    """GUARD-10: query exactly 1000 chars is accepted; not raised, not truncated."""
    query = "x" * MAX_QUERY_LENGTH
    assert MAX_QUERY_LENGTH == 1000
    validate_query_length(query)  # must not raise
    assert len(query) == 1000  # input unchanged


def test_guard_11_1001_chars_rejected():
    """GUARD-11: query 1001 chars raises ERR_QUERY_PARSE_FAILED with HTTP 400."""
    query = "x" * (MAX_QUERY_LENGTH + 1)
    with pytest.raises(InputValidationError) as exc:
        validate_query_length(query)
    assert exc.value.code == "ERR_QUERY_PARSE_FAILED"
    assert exc.value.http_status == 400


def test_zero_and_short_queries_accepted():
    validate_query_length("")
    validate_query_length("hello world")
