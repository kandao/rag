import argparse
import asyncio
import json
import logging
from pathlib import Path

from config import settings
from pipeline.index import ensure_local_indexes
from pipeline.runner import run_local_ingestion

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local file ingestion runner")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest local markdown/text files")
    ingest.add_argument("--input", required=True, help="File or directory to ingest")
    ingest.add_argument(
        "--glob",
        default="*.md,*.txt",
        help="Comma-separated glob patterns when --input is a directory",
    )
    ingest.add_argument(
        "--acl-policy",
        required=True,
        help="Path to acl-policies.yaml",
    )
    ingest.add_argument(
        "--default-clearance",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="Fallback sensitivity level if no ACL policy rule matches",
    )
    ingest.add_argument("--es-url", default="http://127.0.0.1:9200")
    ingest.add_argument("--dry-run", action="store_true")
    ingest.add_argument("--limit", type=int)
    ingest.add_argument("--force-reindex", action="store_true")
    ingest.add_argument(
        "--force-sensitivity",
        type=int,
        choices=[0, 1, 2, 3],
        help="Override final sensitivity level after risk scan and ACL policy selection",
    )
    ingest.add_argument(
        "--override-allowed-groups",
        help="Comma-separated ACL groups to apply to every ingested document",
    )
    ingest.add_argument(
        "--language",
        default="auto",
        choices=["auto", "zh", "ja"],
        help="Chunking language override for CJK documents",
    )
    ingest.add_argument(
        "--embedding-provider",
        default="settings",
        choices=["settings", "openai"],
        help="Use configured embedding settings or force both tiers to OpenAI",
    )
    ingest.add_argument(
        "--embedding-api-url",
        default="https://api.openai.com/v1/embeddings",
        help="Embedding API URL used when --embedding-provider=openai",
    )
    ingest.add_argument(
        "--embedding-model",
        default="text-embedding-3-small",
        help="Embedding model used when --embedding-provider=openai",
    )
    ingest.add_argument(
        "--embedding-api-key-env-l0l1",
        default="EMBEDDING_API_KEY_L0L1",
        help="API key env var for L0/L1 embeddings",
    )
    ingest.add_argument(
        "--embedding-api-key-env-l2l3",
        default="EMBEDDING_API_KEY_L2L3",
        help="API key env var for L2/L3 embeddings",
    )

    init_indexes = subparsers.add_parser(
        "init-indexes",
        help="Create local Elasticsearch indexes and aliases",
    )
    init_indexes.add_argument("--es-url", default="http://127.0.0.1:9200")
    init_indexes.add_argument(
        "--mapping-dir",
        default="deploy/charts/rag/files/mappings",
        help="Directory containing l0l1-mapping.json and l2l3-mapping.json",
    )

    return parser


def _apply_embedding_args(args: argparse.Namespace) -> None:
    if getattr(args, "embedding_provider", "settings") != "openai":
        return

    settings.embedding_provider_l0l1 = "openai"
    settings.embedding_api_url_l0l1 = args.embedding_api_url
    settings.embedding_model_l0l1 = args.embedding_model
    settings.embedding_dims_l0l1 = 1536
    settings.embedding_api_key_env_l0l1 = args.embedding_api_key_env_l0l1

    settings.embedding_provider_l2l3 = "openai"
    settings.embedding_api_url_l2l3 = args.embedding_api_url
    settings.embedding_model_l2l3 = args.embedding_model
    settings.embedding_dims_l2l3 = 1024
    settings.embedding_api_key_env_l2l3 = args.embedding_api_key_env_l2l3


async def _run(args: argparse.Namespace) -> int:
    if args.command == "init-indexes":
        statuses = await ensure_local_indexes(
            es_url=args.es_url,
            mapping_dir=Path(args.mapping_dir),
        )
        print(json.dumps(statuses, indent=2, sort_keys=True))
        return 0

    if args.command == "ingest":
        _apply_embedding_args(args)
        results = await run_local_ingestion(
            input_path=args.input,
            acl_policy_path=args.acl_policy,
            es_url=args.es_url,
            glob_patterns=args.glob,
            default_clearance=args.default_clearance,
            dry_run=args.dry_run,
            limit=args.limit,
            force_reindex=args.force_reindex,
            language=args.language,
            force_sensitivity=args.force_sensitivity,
            override_allowed_groups=(
                [g.strip() for g in args.override_allowed_groups.split(",") if g.strip()]
                if args.override_allowed_groups
                else None
            ),
        )
        print(json.dumps([r.__dict__ for r in results], indent=2, sort_keys=True))
        if any(r.quarantined for r in results):
            return 2
        return 0

    raise ValueError(f"Unsupported command: {args.command}")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
