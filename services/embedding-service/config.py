from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_name: str = "BAAI/bge-m3"
    batch_size: int = 32
    max_seq_len: int = 8192
    log_level: str = "info"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
