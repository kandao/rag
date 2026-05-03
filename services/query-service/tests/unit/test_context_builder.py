from rag_common.models.retrieval import CitationHint, RetrievalCandidate
from internal.modelgateway.context_builder import build_system_prompt, minimize_context


def _c(cid: str, sensitivity: int, content: str = "text content") -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=cid, doc_id="d1", content=content,
        citation_hint=CitationHint(path="doc.pdf", page_number=1, section="Intro"),
        topic="t", doc_type="dt", acl_key="k", sensitivity_level=sensitivity,
        retrieval_score=0.9, source_index="public_index",
    )


def test_mg_08_l0_top_5():
    candidates = [_c(f"c{i}", 0) for i in range(6)]
    chunks = minimize_context(candidates, max_sensitivity_level=0)
    assert len(chunks) == 5


def test_mg_09_l2_top_3():
    candidates = [_c(f"c{i}", 2) for i in range(4)]
    chunks = minimize_context(candidates, max_sensitivity_level=2)
    assert len(chunks) == 3


def test_mg_04_no_acl_fields_in_prompt():
    candidates = [_c("c1", 0, "some content")]
    chunks = minimize_context(candidates, 0)
    prompt = build_system_prompt(chunks)
    assert "acl_tokens" not in prompt
    assert "allowed_groups" not in prompt
    assert "acl_key" not in prompt
    assert "sensitivity_level" not in prompt
    assert "some content" in prompt


def test_mg_07_acl_metadata_absent_from_model_input():
    """MG-07: ACL metadata never included in model prompt — confirmed by prompt construction."""
    candidates = [_c(f"c{i}", i % 3, f"chunk content {i}") for i in range(5)]
    chunks = minimize_context(candidates, max_sensitivity_level=2)
    prompt = build_system_prompt(chunks)
    for field in ("acl_tokens", "allowed_groups", "acl_key", "acl_version", "sensitivity_level"):
        assert field not in prompt


def test_mg_04_extra_acl_fields_stripped():
    """MG-04: even if a candidate carries leaked acl_tokens/allowed_groups
    (e.g. a raw ES _source dict slipping through), minimize_context + build_system_prompt
    must produce a prompt that contains none of those values."""
    leaky = _c("c-leak", 1, "the body content of the chunk")
    # Smuggle ACL fields onto the model instance the way an unsanitized projection might
    object.__setattr__(leaky, "acl_tokens", ["group:eng:secret-token"])
    object.__setattr__(leaky, "allowed_groups", ["eng:secret-org"])
    object.__setattr__(leaky, "acl_key", "acl-key-leak")

    chunks = minimize_context([leaky], max_sensitivity_level=1)
    prompt = build_system_prompt(chunks)

    # Field names absent
    for field in ("acl_tokens", "allowed_groups", "acl_key"):
        assert field not in prompt
    # Field VALUES absent — even if the names were renamed, the secrets must not leak
    for value in ("group:eng:secret-token", "eng:secret-org", "acl-key-leak"):
        assert value not in prompt
    # Sanity: legitimate content still made it through
    assert "the body content of the chunk" in prompt
