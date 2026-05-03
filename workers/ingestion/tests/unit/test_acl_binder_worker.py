import pytest

from rag_common.acl.acl_key import compute_acl_key
from schemas import ACLPolicy


def _job_with_acl(enriched_job, allowed_groups=None, allowed_roles=None):
    policy = ACLPolicy(
        allowed_groups=allowed_groups or [],
        allowed_roles=allowed_roles or [],
        acl_tokens=[],
        acl_key="",
        acl_version="v1",
    ) if (allowed_groups or allowed_roles) else None
    return enriched_job.model_copy(update={"acl_policy": policy, "sensitivity_level": 1})


@pytest.mark.asyncio
async def test_acl_binder_no_policy_empty_tokens(enriched_job):
    from workers.acl_binder_worker import ACLBinderWorker
    job = _job_with_acl(enriched_job)  # no policy
    worker = ACLBinderWorker()
    result = await worker.process(job)

    assert result.acl_policy is not None
    assert result.acl_policy.acl_tokens == []
    expected_key = compute_acl_key(sorted_tokens=[], token_schema_version="v1", acl_version="v1")
    assert result.acl_policy.acl_key == expected_key
    assert result.stage == "acl_binder"


@pytest.mark.asyncio
async def test_acl_binder_with_groups(enriched_job):
    from workers.acl_binder_worker import ACLBinderWorker
    job = _job_with_acl(enriched_job, allowed_groups=["eng:infra@company.com"])
    worker = ACLBinderWorker()
    result = await worker.process(job)

    assert result.acl_policy.acl_tokens != []
    assert result.acl_policy.acl_key != ""
    assert result.stage == "acl_binder"


@pytest.mark.asyncio
async def test_acl_binder_tokens_match_query_side(enriched_job):
    """ING-10: doc-side tokens must match query-side tokens for same groups."""
    from rag_common.acl.token_compression import compress_groups_to_tokens
    from workers.acl_binder_worker import ACLBinderWorker

    groups = ["eng:infra@company.com", "data:analytics@company.com"]
    job = _job_with_acl(enriched_job, allowed_groups=groups)
    worker = ACLBinderWorker()
    result = await worker.process(job)

    expected_tokens = set(compress_groups_to_tokens(groups))
    actual_tokens = set(result.acl_policy.acl_tokens)
    assert expected_tokens == actual_tokens


@pytest.mark.asyncio
async def test_acl_binder_with_roles(enriched_job):
    from workers.acl_binder_worker import ACLBinderWorker
    job = _job_with_acl(enriched_job, allowed_roles=["admin"])
    worker = ACLBinderWorker()
    result = await worker.process(job)

    assert "role:admin" in result.acl_policy.acl_tokens
