from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/jawara"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    waha_api_url: str = "http://localhost:3000"
    waha_api_key: str = "changeme"


@lru_cache
def get_settings() -> Settings:
    return Settings()
