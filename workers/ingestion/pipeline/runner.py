import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from elasticsearch import AsyncElasticsearch

from schemas import IngestionJob

from .acl_bind import bind_acl_job, load_acl_policies, policy_to_acl_policy, select_acl_policy
from .chunk import chunk_job
from .embed import embed_job
from .enrich import enrich_job
from .index import build_bulk_operations, index_job
from .parse import extract_markdown_frontmatter, parse_job
from .risk_scan import scan_job


@dataclass(frozen=True)
class LocalIngestionResult:
    source_path: str
    job_id: str
    stage: str
    sensitivity_level: int
    chunk_count: int
    indexed: bool
    quarantined: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".pdf":
        return "pdf"
    return "db_export"


def discover_input_files(
    input_path: str | Path,
    *,
    glob_patterns: str = "*.md,*.txt",
    limit: int | None = None,
) -> list[Path]:
    path = Path(input_path)
    if path.is_file():
        files = [path]
    else:
        patterns = [p.strip() for p in glob_patterns.split(",") if p.strip()]
        found: dict[Path, None] = {}
        for pattern in patterns:
            for candidate in path.rglob(pattern):
                if candidate.is_file():
                    found[candidate] = None
        files = sorted(found.keys())

    if limit is not None:
        files = files[:limit]
    return files


def make_local_job(path: Path, *, root: Path, language: str = "auto") -> IngestionJob:
    now = _now()
    relative_path = path.relative_to(root).as_posix() if root in path.parents else path.name
    source_type = _source_type_for(path)
    metadata = {
        "path": relative_path,
        "source_relative_path": relative_path,
        "filename": path.name,
        "source": "local",
        "language": language,
    }
    if source_type == "pdf":
        raw_content = None
        raw_content_bytes = path.read_bytes()
    else:
        raw_content = path.read_text(encoding="utf-8")
        raw_content_bytes = None
        if source_type == "markdown":
            frontmatter, _ = extract_markdown_frontmatter(raw_content)
            metadata.update(frontmatter)
    return IngestionJob(
        job_id=str(uuid.uuid4()),
        source_type=source_type,
        source_uri=relative_path,
        source_metadata=metadata,
        raw_content=raw_content,
        raw_content_bytes=raw_content_bytes,
        stage="connector",
        created_at=now,
        updated_at=now,
    )


def apply_acl_policy(
    job: IngestionJob,
    *,
    acl_policies: list[dict],
    default_clearance: int,
) -> IngestionJob:
    relative_path = job.source_metadata.get("source_relative_path", job.source_uri)
    selected = select_acl_policy(acl_policies, relative_path)
    policy = policy_to_acl_policy(selected)
    policy_sensitivity = (
        int(selected["sensitivity_level"])
        if selected is not None and "sensitivity_level" in selected
        else default_clearance
    )
    sensitivity = max(job.sensitivity_level or 0, policy_sensitivity)
    return job.model_copy(update={"acl_policy": policy, "sensitivity_level": sensitivity})


async def run_local_ingestion(
    *,
    input_path: str | Path,
    acl_policy_path: str | Path,
    es_url: str,
    glob_patterns: str = "*.md,*.txt",
    default_clearance: int = 0,
    dry_run: bool = False,
    limit: int | None = None,
    force_reindex: bool = False,
    language: str = "auto",
    force_sensitivity: int | None = None,
    override_allowed_groups: list[str] | None = None,
) -> list[LocalIngestionResult]:
    input_root = Path(input_path)
    root = input_root if input_root.is_dir() else input_root.parent
    files = discover_input_files(input_root, glob_patterns=glob_patterns, limit=limit)
    acl_policies = load_acl_policies(acl_policy_path)
    results: list[LocalIngestionResult] = []

    es_client = None
    http_client = None
    if not dry_run:
        es_client = AsyncElasticsearch(hosts=es_url.split(","))
        http_client = httpx.AsyncClient()

    try:
        for path in files:
            job = make_local_job(path, root=root, language=language)
            job = parse_job(job)
            risk = scan_job(job)
            if risk.quarantined_job is not None:
                results.append(
                    LocalIngestionResult(
                        source_path=str(path),
                        job_id=job.job_id,
                        stage="quarantined",
                        sensitivity_level=job.sensitivity_level or 0,
                        chunk_count=0,
                        indexed=False,
                        quarantined=True,
                    )
                )
                continue

            job = risk.job
            if job is None:
                continue
            job = chunk_job(job)
            job = enrich_job(job)
            job = apply_acl_policy(
                job,
                acl_policies=acl_policies,
                default_clearance=default_clearance,
            )
            if force_sensitivity is not None:
                job = job.model_copy(update={"sensitivity_level": force_sensitivity})
            if override_allowed_groups is not None and job.acl_policy is not None:
                job = job.model_copy(
                    update={
                        "acl_policy": job.acl_policy.model_copy(
                            update={"allowed_groups": override_allowed_groups}
                        )
                    }
                )
            job = bind_acl_job(job)

            if dry_run:
                build_bulk_operations(job, force_reindex=force_reindex)
                results.append(
                    LocalIngestionResult(
                        source_path=str(path),
                        job_id=job.job_id,
                        stage=job.stage,
                        sensitivity_level=job.sensitivity_level or 0,
                        chunk_count=len(job.chunks),
                        indexed=False,
                    )
                )
                continue

            job = await embed_job(job, http_client=http_client)
            indexed_job = await index_job(
                job,
                es_client=es_client,
                force_reindex=force_reindex,
            )
            if indexed_job is None:
                raise RuntimeError(f"No chunks indexed for {path}")
            results.append(
                LocalIngestionResult(
                    source_path=str(path),
                    job_id=indexed_job.job_id,
                    stage=indexed_job.stage,
                    sensitivity_level=indexed_job.sensitivity_level or 0,
                    chunk_count=len(indexed_job.chunks),
                    indexed=True,
                )
            )
    finally:
        if http_client is not None:
            await http_client.aclose()
        if es_client is not None:
            await es_client.close()

    return results
