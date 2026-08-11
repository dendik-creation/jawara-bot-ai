from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py → core → app → backend → repo root. The single `.env` at the root is
# what Compose reads, so a locally run gateway/worker must read the same file or
# the two halves of the stack silently disagree on credentials.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # Root `.env` first, then a `backend/.env` if one exists — later files win,
    # so a developer can override one value without copying the whole file.
    # Real environment variables still outrank both, which is how Compose keeps
    # injecting in-network hostnames.
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", ".env"),
        extra="ignore",
    )

    # Connection strings are derived from the component variables below when they
    # are not set explicitly (see `_derive_connection_urls`). Compose sets them
    # explicitly with in-network hostnames; a local process gets `localhost` and
    # the credentials from the root `.env`.
    database_url: str = ""
    redis_url: str = ""
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    waha_api_url: str = ""
    waha_api_key: str = "changeme"

    # Components of the derived URLs. These are the variables the root `.env`
    # already carries for Compose, reused here so local runs need no second copy.
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "jawara"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    redis_host: str = "localhost"
    redis_port: int = 6379
    waha_host: str = "localhost"
    waha_port: int = 3000

    # Celery broker/backend default to the same Redis instance, separate logical DBs
    # so queued jobs and task results never collide on a FLUSHDB of either.
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    celery_queue_name: str = "jawara.messages"
    celery_max_retries: int = 3
    celery_retry_backoff_seconds: int = 2
    celery_retry_backoff_max_seconds: int = 60
    # Separate queue for Training Jobs (05_Training_Jobs §6's own recommendation)
    # so a long training run never parks message-pipeline jobs behind it.
    celery_training_queue_name: str = "jawara.training"
    # Same isolation reasoning, one level down: a long training run shouldn't
    # park evaluation jobs behind it either (06_Model_Evaluation.md).
    celery_evaluation_queue_name: str = "jawara.evaluation"

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
    ml_service_url: str = ""
    ml_service_host: str = "localhost"
    ml_service_port: int = 9000
    ml_service_api_key: str = "changeme"
    # Per-endpoint budgets, carved out of the <3.0s end-to-end target. classify
    # is tighter than generate because generation is the one call that cannot be
    # retried blindly.
    ml_timeout_classify_seconds: float = 2.0
    ml_timeout_embed_seconds: float = 3.0
    ml_timeout_rag_seconds: float = 3.0
    ml_timeout_generate_seconds: float = 8.0
    # /v1/train doesn't exist in ml-service yet (05_Training_Jobs, Planned) — a
    # short timeout so a training-job task fails fast and honestly instead of
    # hanging on a route that will never answer.
    ml_timeout_train_seconds: float = 5.0
    # /v1/evaluate doesn't exist in ml-service yet either (06_Model_Evaluation,
    # Planned) — same short-timeout-for-honest-failure reasoning as train.
    ml_timeout_evaluate_seconds: float = 5.0
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

    # Group behaviour. In a group the bot answers only when it is addressed —
    # mentioned or replied to (01_Overview/04_How_it_Works §101). Replying to
    # every message in a family group is spam and gets the number banned.
    # Setting this false makes it answer everything, which is only sane in a
    # throwaway test group.
    group_reply_requires_trigger: bool = True
    # Comma-separated JIDs this bot answers to, e.g.
    # `6281234567890@c.us,249117464891485@lid`. Normally discovered from WAHA;
    # this is the override for when that lookup cannot be made.
    bot_whatsapp_ids: str = ""

    # WhatsApp dispatch (WAHA REST). A live group send under real webhook
    # contention measured 7.6s to complete — WEBJS resolving a group/@lid
    # participant it has not seen before is not instant. 5s was too tight:
    # the client aborted mid-flight, and WAHA logged the abort as "request
    # aborted" at 5007ms, meaning it was still working, not stuck. Aborting
    # and retrying wastes whatever progress WAHA had made, so a longer single
    # budget beats more short ones. See [[Open_Decisions_Carried_Forward]] §3.1.
    waha_send_timeout_seconds: float = 15.0
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

    # Operator authentication (09_Security/06_Platform_Security_Requirements §1).
    # Every Control Panel endpoint requires a session token; there is no
    # deployment-wide shared secret and no "empty means open" mode, because a
    # gate that can be disabled by leaving a variable blank eventually is.
    #
    # 8 hours: one working shift. Long enough that an operator is not re-typing
    # a password between incidents, short enough that a stolen token dies the
    # same day.
    auth_session_ttl_minutes: int = 480
    # bcrypt cost. Raise as hardware improves — existing hashes carry their own
    # cost and keep verifying.
    auth_bcrypt_rounds: int = 12
    # Login attempts per (email, client IP) inside the window. Deliberately far
    # below the webhook budget: humans do not type a password 20 times a minute.
    auth_login_max_attempts: int = 5
    auth_login_window_seconds: int = 300

    log_level: str = "INFO"

    @model_validator(mode="after")
    def _derive_connection_urls(self) -> "Settings":
        """Fill the connection strings nobody set from their component parts.

        A locally run gateway or worker used to fall back to hardcoded
        placeholders (`postgres:postgres@localhost/jawara`, `http://ml-service:9000`),
        which fail in two different and confusing ways: an
        `InvalidPasswordError` against a database that does exist, and an
        unresolvable Docker hostname. Deriving from `POSTGRES_*` / `REDIS_*` /
        `ML_SERVICE_PORT` — the variables the root `.env` already defines — makes
        the local default correct instead of merely plausible.

        Only fields the caller left untouched are derived: `model_fields_set`
        contains anything supplied by environment, `.env` file, or constructor,
        so Compose's explicit in-network URLs always win.
        """
        set_fields = self.model_fields_set

        if "database_url" not in set_fields or not self.database_url:
            self.database_url = (
                f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        if "redis_url" not in set_fields or not self.redis_url:
            self.redis_url = f"redis://{self.redis_host}:{self.redis_port}/0"
        if "celery_broker_url" not in set_fields or not self.celery_broker_url:
            self.celery_broker_url = f"redis://{self.redis_host}:{self.redis_port}/0"
        if "celery_result_backend" not in set_fields or not self.celery_result_backend:
            self.celery_result_backend = f"redis://{self.redis_host}:{self.redis_port}/1"
        if "waha_api_url" not in set_fields or not self.waha_api_url:
            self.waha_api_url = f"http://{self.waha_host}:{self.waha_port}"
        if "ml_service_url" not in set_fields or not self.ml_service_url:
            self.ml_service_url = f"http://{self.ml_service_host}:{self.ml_service_port}"
        return self

    @property
    def bot_whatsapp_id_list(self) -> list[str]:
        return [jid.strip() for jid in self.bot_whatsapp_ids.split(",") if jid.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
