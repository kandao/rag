import pytest


@pytest.mark.asyncio
async def test_local_ingestion_dry_run_binds_acl_and_chunks(tmp_path):
    docs = tmp_path / "docs"
    policy_path = tmp_path / "acl-policies.yaml"
    internal = docs / "internal"
    internal.mkdir(parents=True)
    doc = internal / "engineering_notes.md"
    doc.write_text(
        "# Engineering Notes\n\nINTERNAL USE ONLY\n\nDeploy the API service with Kubernetes.",
        encoding="utf-8",
    )
    policy_path.write_text(
        """
acl_policies:
  - source_pattern: "internal/engineering_*"
    allowed_groups: ["eng:engineering"]
    allowed_roles: []
    sensitivity_level: 1
""".strip(),
        encoding="utf-8",
    )

    from pipeline.runner import run_local_ingestion

    results = await run_local_ingestion(
        input_path=docs,
        acl_policy_path=policy_path,
        es_url="http://127.0.0.1:9200",
        dry_run=True,
    )

    assert len(results) == 1
    assert results[0].indexed is False
    assert results[0].sensitivity_level == 1
    assert results[0].chunk_count >= 1


def test_make_local_job_records_language(tmp_path):
    from pipeline.runner import make_local_job

    doc = tmp_path / "kanji.md"
    doc.write_text("# 安全運用基準\n\n安全運用基準を確認する。", encoding="utf-8")

    job = make_local_job(doc, root=tmp_path, language="ja")

    assert job.source_metadata["language"] == "ja"


def test_index_doc_contains_query_service_fields(enriched_job):
    from schemas import ACLPolicy
    from pipeline.index import build_bulk_operations

    policy = ACLPolicy(
        allowed_groups=["eng:public"],
        allowed_roles=[],
        acl_tokens=["group:eng:public"],
        acl_key="key",
        acl_version="v1",
    )
    chunks = [c.model_copy(update={"vector": [0.1] * 1536}) for c in enriched_job.chunks]
    job = enriched_job.model_copy(
        update={
            "chunks": chunks,
            "acl_policy": policy,
            "sensitivity_level": 0,
            "source_metadata": {
                "path": "public/product_overview.md",
                "topic": "engineering",
                "doc_type": "policy",
            },
        }
    )

    operations = build_bulk_operations(job)
    doc = operations[1]

    assert doc["chunk_id"]
    assert doc["doc_id"]
    assert doc["content"]
    assert doc["path"] == "public/product_overview.md"
    assert doc["topic"] == "engineering"
    assert doc["doc_type"] == "policy"
    assert doc["acl_tokens"] == ["group:eng:public"]
    assert doc["acl_key"] == "key"
    assert doc["acl_version"] == "v1"
    assert doc["sensitivity_level"] == 0
    assert doc["vector"]
    assert doc["created_at"]
    assert doc["updated_at"]
