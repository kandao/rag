from typing import Literal
from pydantic import BaseModel, model_validator

IngestionStage = Literal[
    "connector",
    "parser",
    "risk_scanner",
    "chunker",
    "metadata_enricher",
    "acl_binder",
    "embedding",
    "indexer",
    "complete",
    "quarantined",
]


class ParsedSection(BaseModel):
    content: str
    page_number: int | None
    section: str | None
    table_cells: list[list[str]] | None = None


class Chunk(BaseModel):
    content: str
    page_number: int | None
    section: str | None
    doc_id: str | None = None      # set by Metadata Enricher
    chunk_id: str | None = None    # set by Metadata Enricher
    vector: list[float] | None = None  # set by Embedding Worker


class ACLPolicy(BaseModel):
    allowed_groups: list[str]
    allowed_roles: list[str]
    acl_tokens: list[str]  # pre-computed; recomputed by ACL Binder if empty
    acl_key: str
    acl_version: str


class IngestionJob(BaseModel):
    job_id: str
    source_type: Literal["pdf", "html", "markdown", "wiki_export", "db_export"]
    source_uri: str
    source_metadata: dict
    raw_content: str | None = None          # text-based formats only
    raw_content_bytes: bytes | None = None  # binary formats (PDF)
    parsed_sections: list[ParsedSection] = []
    chunks: list[Chunk] = []
    sensitivity_level: int | None = None   # set by Risk Scanner
    acl_policy: ACLPolicy | None = None    # set by ACL Binder
    stage: IngestionStage
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def validate_content_exclusivity(self) -> "IngestionJob":
        if self.raw_content is not None and self.raw_content_bytes is not None:
            raise ValueError("raw_content and raw_content_bytes are mutually exclusive")
        return self
