import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    log_level: str = "info"
    service_name: str = "query-service"
    environment: str = "production"

    token_schema_version: str = "v1"
    acl_version: str = "v1"
    acl_token_max_count: int = 30
    claims_signing_key: str = ""

    redis_host: str = "redis.retrieval-deps"
    redis_port: int = 6379
    redis_auth_cache_ttl_s: int = 300
    result_cache_ttl_s: int = 60
    embedding_cache_ttl_s: int = 3600

    es_hosts: str = "https://elasticsearch.retrieval-deps:9200"
    es_username: str = ""
    es_password: str = ""

    reranker_url: str = "http://reranker-service.reranker:8080"
    reranker_enabled: bool = True
    reranker_timeout_ms: int = 1000

    audit_es_hosts: str = "https://audit-elasticsearch.retrieval-deps:9200"
    audit_es_username: str = ""
    audit_es_password: str = ""
    audit_index_alias: str = "audit-events-current"
    audit_write_timeout_ms: int = 5000
    audit_fail_closed_min_clearance: int = 2

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
