"""Input-level validation that runs before the Guard checks.

GUARD-10 / GUARD-11: query length must be ≤ 1000 chars.
"""

MAX_QUERY_LENGTH = 1000


class InputValidationError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        self.code = code
        self.http_status = http_status
        super().__init__(message)


def validate_query_length(query: str) -> None:
    """Raise InputValidationError if the query exceeds MAX_QUERY_LENGTH."""
    if len(query) > MAX_QUERY_LENGTH:
        raise InputValidationError(
            "ERR_QUERY_PARSE_FAILED",
            f"query exceeds {MAX_QUERY_LENGTH} characters",
        )
