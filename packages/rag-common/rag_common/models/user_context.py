from pydantic import BaseModel, model_validator


class UserContext(BaseModel):
    user_id: str
    effective_groups: list[str]
    effective_clearance: int  # 0–3 (L0=0 … L3=3)
    acl_tokens: list[str]     # bounded ≤ 30; used in ES filter
    acl_key: str              # hex SHA-256
    token_schema_version: str  # encoding schema version (e.g. "v1")
    acl_version: str           # policy-change sequence number (e.g. "v1")
    claims_hash: str           # SHA-256 of raw claims; Redis auth-cache key
    derived_at: str            # ISO-8601 UTC

    @model_validator(mode="after")
    def validate_clearance_range(self) -> "UserContext":
        if not (0 <= self.effective_clearance <= 3):
            raise ValueError("effective_clearance must be 0–3")
        return self

    @model_validator(mode="after")
    def validate_acl_tokens_bound(self) -> "UserContext":
        if len(self.acl_tokens) > 30:
            raise ValueError("acl_tokens must contain ≤ 30 entries")
        return self
