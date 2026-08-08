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

    # Celery broker/backend default to the same Redis instance, separate logical DBs
    # so queued jobs and task results never collide on a FLUSHDB of either.
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_queue_name: str = "jawara.messages"
    celery_max_retries: int = 3
    celery_retry_backoff_seconds: int = 2
    celery_retry_backoff_max_seconds: int = 60

    # Sliding-window webhook rate limit, per (session, chat) pair.
    # 20 req / 60s: a user forwarding a batch of ~10 messages passes untouched,
    # a sustained flood is cut off. See 07_How_to_Run/01_Dev_Environtment.
    rate_limit_enabled: bool = True
    rate_limit_max_requests: int = 20
    rate_limit_window_seconds: int = 60

    # SHA-256(user_hash_salt + identifier) — see app/core/hashing.py.
    user_hash_salt: str = "changeme"

    qdrant_collection: str = "fact_knowledge_base"
    # 1536 = text-embedding-3-small, 768 = IndoBERT
    embedding_dim: int = 1536
    qdrant_hnsw_m: int = 16
    qdrant_hnsw_ef_construct: int = 100

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
