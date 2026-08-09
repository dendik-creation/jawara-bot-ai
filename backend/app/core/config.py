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

    # `message_logs.extracted_text` holds message content in plaintext and has no
    # retention policy yet (01_Documentation_Audit_Report finding #1). Setting
    # this to false keeps the audit trail — intent, risk, latency — without
    # storing what the user actually wrote.
    log_message_content: bool = True

    qdrant_collection: str = "fact_knowledge_base"
    # 1536 = text-embedding-3-small, 768 = IndoBERT
    embedding_dim: int = 1536
    qdrant_hnsw_m: int = 16
    qdrant_hnsw_ef_construct: int = 100

    # Intent router sensitivity. Confidence is the winning category's share of
    # total score, so the threshold is "how dominant must the winner be", not a
    # model probability. Tunable by operators without a redeploy.
    intent_confidence_threshold: float = 0.45
    intent_min_score: float = 1.5

    # ML Service (standalone). The gateway reaches it only through
    # app/clients/ml_client.py — see 02_Architecture/04_ML_Service.md §3.
    ml_service_url: str = "http://ml-service:9000"
    ml_service_api_key: str = "changeme"
    # Per-endpoint budgets, carved out of the <3.0s end-to-end target. classify
    # is tighter than generate because generation is the one call that cannot be
    # retried blindly.
    ml_timeout_classify_seconds: float = 2.0
    ml_timeout_embed_seconds: float = 3.0
    ml_timeout_rag_seconds: float = 3.0
    ml_timeout_generate_seconds: float = 8.0
    ml_enabled: bool = True

    # RAG retrieval contract, fixed by 03_Database/02_VectorDB_Specifications.md.
    rag_top_k: int = 3
    rag_score_threshold: float = 0.80

    # External threat intelligence. Absent keys disable the provider rather than
    # failing the pipeline: a missing key is a configuration state, not an error.
    google_safe_browsing_api_key: str = ""
    virustotal_api_key: str = ""
    url_scan_timeout_seconds: float = 3.0
    # Verdicts are cached in Redis: both providers have hard free-tier quotas and
    # the same forwarded link arrives many times over.
    url_scan_cache_ttl_seconds: int = 3600
    url_scan_max_urls: int = 5
    # VirusTotal aggregates ~90 engines; a single detection is often a false
    # positive, two is a signal. Configurable because the right cut-off depends
    # on how much operator review capacity exists.
    virustotal_high_threshold: int = 2

    # WhatsApp dispatch (WAHA REST).
    waha_send_timeout_seconds: float = 5.0
    waha_send_max_attempts: int = 2
    waha_send_retry_backoff_seconds: float = 0.5
    # End-to-end KPI from 03_Pitching_Narrative; exceeding it logs a warning
    # rather than failing the send — the user still needs their answer.
    end_to_end_target_ms: int = 3000

    # Control Panel. Explicit origin list, never a wildcard
    # (09_Security/06_Platform_Security_Requirements §1).
    cors_allow_origins: str = "http://localhost:3001,http://localhost:3000"
    dashboard_window_hours: int = 24
    dashboard_activity_limit: int = 25
    # Stopgap shared secret until operator auth + RBAC exist (Phase 2). Empty
    # means open, which is fine for a local dev stack and not fine in production.
    dashboard_api_key: str = ""

    log_level: str = "INFO"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
