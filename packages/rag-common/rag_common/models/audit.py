from typing import Literal
from pydantic import BaseModel


class AuditEvent(BaseModel):
    event_id: str                  # uuid-v4
    request_id: str
    timestamp: str                 # ISO-8601 UTC
    user_id: str
    claims_digest: str             # SHA-256 of raw claims
    acl_key: str
    acl_version: str
    target_indexes: list[str]
    retrieved_chunk_ids: list[str]
    ranked_chunk_ids: list[str]
    sensitivity_levels_accessed: list[int]
    model_path: str                # e.g. "cloud_l1" | "private_l2" | "private_l3"
    authorization_decision: Literal["allowed", "denied", "fail_closed"]
    query_risk_signal: str
    answer_returned: bool
    latency_ms: int
