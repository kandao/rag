from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mock_users_file: str = "../../test/fixtures/mock-users.yaml"
    claims_signing_key: str = "dev-signing-key-change-in-production"
    query_service_url: str = "http://query-service.query:8080"
    log_level: str = "info"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
