import json
from pathlib import Path
from typing import Any

from elasticsearch import AsyncElasticsearch

from config import settings
from schemas import IngestionJob

INDEX_BY_SENSITIVITY = {
    0: "public_index",
    1: "internal_index",
    2: "confidential_index",
    3: "restricted_index",
}

LOCAL_INDEXES = {
    "public_index": ("public_index_v1", "l0l1-mapping.json"),
    "internal_index": ("internal_index_v1", "l0l1-mapping.json"),
    "confidential_index": ("confidential_index_v1", "l2l3-mapping.json"),
    "restricted_index": ("restricted_index_v1", "l2l3-mapping.json"),
}


_SEC_METADATA_FIELDS = [
    "ticker",
    "company",
    "cik",
    "form",
    "report_date",
    "filing_date",
    "accession_number",
    "source_url",
]


def _content_with_search_context(chunk, metadata: dict) -> str:
    header_parts = []
    for key in ["ticker", "company", "form", "report_date"]:
        value = metadata.get(key)
        if value:
            label = key.replace("_", " ").title()
            header_parts.append(f"{label}: {value}")
    if chunk.section:
        header_parts.append(f"Section: {chunk.section}")

    if not header_parts:
        return chunk.content
    return "\n".join(header_parts) + "\n\n" + chunk.content


def chunk_to_es_doc(chunk, job: IngestionJob, acl_tokens: list[str], acl_key: str) -> dict:
    metadata = job.source_metadata or {}
    path = metadata.get("path") or metadata.get("source_relative_path") or job.source_uri
    doc = {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "content": _content_with_search_context(chunk, metadata),
        "path": path,
        "source_uri": job.source_uri,
        "source_type": job.source_type,
        "source": metadata.get("source", "local"),
        "topic": metadata.get("topic", "general"),
        "doc_type": metadata.get("doc_type", "document"),
        "year": metadata.get("year"),
        "allowed_groups": job.acl_policy.allowed_groups if job.acl_policy else [],
        "acl_tokens": acl_tokens,
        "acl_key": acl_key,
        "acl_version": job.acl_policy.acl_version if job.acl_policy else settings.acl_version,
        "sensitivity_level": job.sensitivity_level or 0,
        "page_number": chunk.page_number,
        "section": chunk.section,
        "vector": chunk.vector,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }
    for field in _SEC_METADATA_FIELDS:
        value = metadata.get(field)
        if value not in (None, ""):
            doc[field] = value
    return doc


def build_bulk_operations(job: IngestionJob, *, force_reindex: bool = False) -> list[dict]:
    sensitivity = job.sensitivity_level or 0
    target_index = INDEX_BY_SENSITIVITY.get(sensitivity, "public_index")

    acl_tokens = job.acl_policy.acl_tokens if job.acl_policy else []
    acl_key = job.acl_policy.acl_key if job.acl_policy else ""

    bulk_body = []
    for chunk in job.chunks:
        if not chunk.chunk_id:
            continue
        op = {"_index": target_index, "_id": chunk.chunk_id}
        bulk_body.append({"index": op})
        bulk_body.append(chunk_to_es_doc(chunk, job, acl_tokens, acl_key))

    return bulk_body


async def index_job(
    job: IngestionJob,
    *,
    es_client: AsyncElasticsearch | None = None,
    es_url: str | None = None,
    force_reindex: bool = False,
) -> IngestionJob | None:
    async def _run(client: AsyncElasticsearch) -> IngestionJob | None:
        bulk_body = build_bulk_operations(job, force_reindex=force_reindex)
        if not bulk_body:
            return None

        result = await client.bulk(operations=bulk_body)
        if result.get("errors"):
            failed = [
                item for item in result["items"]
                if item.get("index", {}).get("error")
            ]
            raise RuntimeError(f"Bulk indexing errors: {failed[:3]}")

        return job.model_copy(update={"stage": "complete"})

    if es_client is not None:
        return await _run(es_client)

    client = AsyncElasticsearch(
        hosts=(es_url or settings.es_hosts).split(","),
        http_auth=(settings.es_username, settings.es_password) if settings.es_username else None,
    )
    try:
        return await _run(client)
    finally:
        await client.close()


async def ensure_local_indexes(
    *,
    es_url: str,
    mapping_dir: str | Path,
    es_client: AsyncElasticsearch | None = None,
) -> dict[str, str]:
    async def _run(client: AsyncElasticsearch) -> dict[str, str]:
        statuses: dict[str, str] = {}
        base = Path(mapping_dir)
        for alias, (physical_index, mapping_file) in LOCAL_INDEXES.items():
            alias_exists = await client.indices.exists_alias(name=alias)
            if alias_exists:
                statuses[alias] = "alias-exists"
                continue

            index_exists = await client.indices.exists(index=physical_index)
            if not index_exists:
                mapping: dict[str, Any] = json.loads((base / mapping_file).read_text())
                await client.indices.create(index=physical_index, body=mapping)
                statuses[physical_index] = "created"
            else:
                statuses[physical_index] = "index-exists"

            await client.indices.put_alias(index=physical_index, name=alias)
            statuses[alias] = "alias-created"

        audit_alias = "audit-events-current"
        audit_index = "audit-events-v1"
        if await client.indices.exists_alias(name=audit_alias):
            statuses[audit_alias] = "alias-exists"
        else:
            if not await client.indices.exists(index=audit_index):
                await client.indices.create(index=audit_index, body={"mappings": {"dynamic": True}})
                statuses[audit_index] = "created"
            await client.indices.put_alias(index=audit_index, name=audit_alias)
            statuses[audit_alias] = "alias-created"
        return statuses

    if es_client is not None:
        return await _run(es_client)

    client = AsyncElasticsearch(hosts=es_url.split(","))
    try:
        return await _run(client)
    finally:
        await client.close()
