from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

from rag_common.acl.acl_key import compute_acl_key
from rag_common.acl.token_compression import compress_groups_to_tokens

from config import settings
from schemas import ACLPolicy, IngestionJob


def normalize_role(role: str) -> str:
    return role.lower().replace(" ", "-").replace("_", "-")


def load_acl_policies(path: str | Path) -> list[dict[str, Any]]:
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("acl_policies", []))


def select_acl_policy(
    policies: list[dict[str, Any]],
    source_relative_path: str,
) -> dict[str, Any] | None:
    normalized = source_relative_path.replace("\\", "/")
    for policy in policies:
        pattern = str(policy.get("source_pattern", ""))
        if fnmatch(normalized, pattern):
            return policy
    return None


def policy_to_acl_policy(policy: dict[str, Any] | None) -> ACLPolicy:
    return ACLPolicy(
        allowed_groups=list((policy or {}).get("allowed_groups", [])),
        allowed_roles=list((policy or {}).get("allowed_roles", [])),
        acl_tokens=[],
        acl_key="",
        acl_version=settings.acl_version,
    )


def bind_acl_job(job: IngestionJob, acl_policy: ACLPolicy | None = None) -> IngestionJob:
    acl_policy = acl_policy or job.acl_policy

    if acl_policy is None or (
        not acl_policy.allowed_groups and not acl_policy.allowed_roles
    ):
        empty_acl_key = compute_acl_key(
            sorted_tokens=[],
            token_schema_version=settings.token_schema_version,
            acl_version=settings.acl_version,
        )
        empty_policy = ACLPolicy(
            allowed_groups=[],
            allowed_roles=[],
            acl_tokens=[],
            acl_key=empty_acl_key,
            acl_version=settings.acl_version,
        )
        return job.model_copy(update={"acl_policy": empty_policy, "stage": "acl_binder"})

    group_tokens = compress_groups_to_tokens(acl_policy.allowed_groups)
    role_tokens = [f"role:{normalize_role(r)}" for r in acl_policy.allowed_roles]
    acl_tokens = list(dict.fromkeys(group_tokens + role_tokens))

    acl_key = compute_acl_key(
        sorted_tokens=sorted(acl_tokens),
        token_schema_version=settings.token_schema_version,
        acl_version=settings.acl_version,
    )

    bound_policy = ACLPolicy(
        allowed_groups=acl_policy.allowed_groups,
        allowed_roles=acl_policy.allowed_roles,
        acl_tokens=acl_tokens,
        acl_key=acl_key,
        acl_version=settings.acl_version,
    )

    return job.model_copy(update={"acl_policy": bound_policy, "stage": "acl_binder"})
