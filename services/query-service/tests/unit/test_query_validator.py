import pytest
from internal.querybuilder.query_validator import assert_acl_present


def _base_query(include_knn: bool = False) -> dict:
    q = {
        "query": {
            "bool": {
                "must": [{"multi_match": {"query": "test", "fields": ["content"]}}],
                "filter": [
                    {"terms": {"acl_tokens": ["group:eng"]}},
                    {"range": {"sensitivity_level": {"lte": 1}}},
                ],
            }
        },
        "size": 100,
    }
    if include_knn:
        q["knn"] = {
            "field": "vector",
            "query_vector": [0.1],
            "k": 10,
            "filter": {"bool": {"filter": [
                {"terms": {"acl_tokens": ["group:eng"]}},
                {"range": {"sensitivity_level": {"lte": 1}}},
            ]}},
        }
    return q


def test_valid_bm25_passes():
    assert_acl_present(_base_query())


def test_valid_hybrid_passes():
    assert_acl_present(_base_query(include_knn=True))


def test_sqb_05_missing_acl_in_knn_raises():
    q = _base_query(include_knn=True)
    q["knn"]["filter"]["bool"]["filter"] = [{"range": {"sensitivity_level": {"lte": 1}}}]
    with pytest.raises(AssertionError, match="acl_tokens filter missing from knn.filter"):
        assert_acl_present(q)


def test_missing_acl_in_bool_raises():
    q = _base_query()
    q["query"]["bool"]["filter"] = [{"range": {"sensitivity_level": {"lte": 1}}}]
    with pytest.raises(AssertionError, match="acl_tokens filter missing from query.bool.filter"):
        assert_acl_present(q)
