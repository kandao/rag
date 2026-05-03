def _has_acl_tokens_filter(filters: list[dict]) -> bool:
    return any("terms" in f and "acl_tokens" in f["terms"] for f in filters)


def _has_sensitivity_filter(filters: list[dict]) -> bool:
    return any("range" in f and "sensitivity_level" in f["range"] for f in filters)


def assert_acl_present(es_query: dict) -> None:
    """Assert that ACL filters are present in every query branch before submission.

    Raises AssertionError (programming error, not user error) if invariant is violated.
    ACL filter missing from any branch would allow unauthorized data to be returned.
    """
    bool_filters: list[dict] = es_query.get("query", {}).get("bool", {}).get("filter", [])

    assert _has_acl_tokens_filter(bool_filters), (
        "INVARIANT VIOLATED: acl_tokens filter missing from query.bool.filter"
    )
    assert _has_sensitivity_filter(bool_filters), (
        "INVARIANT VIOLATED: sensitivity_level filter missing from query.bool.filter"
    )

    knn = es_query.get("knn")
    if knn is not None:
        knn_filters: list[dict] = knn.get("filter", {}).get("bool", {}).get("filter", [])
        assert _has_acl_tokens_filter(knn_filters), (
            "INVARIANT VIOLATED: acl_tokens filter missing from knn.filter"
        )
        assert _has_sensitivity_filter(knn_filters), (
            "INVARIANT VIOLATED: sensitivity_level filter missing from knn.filter"
        )
