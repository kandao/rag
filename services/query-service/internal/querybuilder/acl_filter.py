from rag_common.models.user_context import UserContext

SOURCE_FIELDS = [
    "doc_id", "chunk_id", "content", "path",
    "page_number", "section", "topic", "doc_type",
    "ticker", "company", "form", "report_date", "filing_date",
    "acl_key", "sensitivity_level",
]


def build_acl_filters(user_context: UserContext) -> list[dict]:
    """Build the two mandatory ACL filter clauses.

    Both must be present in every query: terms filter on acl_tokens AND range filter on
    sensitivity_level. An empty acl_tokens list returns zero results by design (fail-closed).
    """
    return [
        {"terms": {"acl_tokens": user_context.acl_tokens}},
        {"range": {"sensitivity_level": {"lte": user_context.effective_clearance}}},
    ]
