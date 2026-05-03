from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Kafka
    kafka_bootstrap_servers: str = "kafka.kafka.svc.cluster.local:9092"
    kafka_consumer_group: str = "ingestion-workers"
    kafka_security_protocol: str = "PLAINTEXT"

    kafka_topic_raw: str = "ingestion.raw"
    kafka_topic_parsed: str = "ingestion.parsed"
    kafka_topic_scanned: str = "ingestion.scanned"
    kafka_topic_quarantine: str = "ingestion.quarantine"
    kafka_topic_chunked: str = "ingestion.chunked"
    kafka_topic_enriched: str = "ingestion.enriched"
    kafka_topic_acl_bound: str = "ingestion.acl_bound"
    kafka_topic_embedded: str = "ingestion.embedded"
    kafka_topic_dlq: str = "ingestion.dlq"

    # Redis
    redis_host: str = "redis.retrieval-deps"
    redis_port: int = 6379

    # Elasticsearch
    es_hosts: str = "https://elasticsearch.retrieval-deps:9200"
    es_username: str = ""
    es_password: str = ""

    # Embedding
    embedding_provider_l0l1: str = "openai"
    embedding_model_l0l1: str = "text-embedding-3-small"
    embedding_dims_l0l1: int = 1536
    embedding_api_url_l0l1: str = "https://api-gateway.company.internal/v1/embeddings"
    embedding_api_key_env_l0l1: str = "EMBEDDING_API_KEY_L0L1"
    embedding_batch_size_l0l1: int = 200

    embedding_provider_l2l3: str = "private"
    embedding_model_l2l3: str = "bge-m3"
    embedding_dims_l2l3: int = 1024
    embedding_api_url_l2l3: str = "http://embedding-service.retrieval-deps:8080/v1/embed"
    embedding_api_key_env_l2l3: str = "EMBEDDING_API_KEY_L2L3"
    embedding_batch_size_l2l3: int = 32
    embedding_timeout_ms: int = 30000

    # Connector
    connector_pull_interval_s: int = 3600
    connector_max_file_size_mb: int = 50

    # ACL
    token_schema_version: str = "v1"
    acl_version: str = "v1"

    # Chunker
    chunk_size_tokens: int = 400
    chunk_overlap_tokens: int = 75
    chunker_tokenizer: str = "cl100k_base"

    log_level: str = "info"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
