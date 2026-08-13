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
    # Fact-check ingestion is network-bound and deliberately slow (it sleeps
    # between requests to stay polite), so it gets its own queue rather than
    # sitting in front of a user's WhatsApp message.
    celery_ingestion_queue_name: str = "jawara.ingestion"

    # Continuous fact-check evidence ingestion (04_AI_and_ML/03_Knowledge_Base.md).
    # Off means Celery Beat schedules nothing; the manual Control Panel
    # trigger still works, so this is "stop crawling", not "remove the
    # feature".
    fact_ingestion_enabled: bool = True
    # Comma-separated adapter slugs, in run order. Unknown slugs fail loudly.
    fact_ingestion_sources: str = "turnbackhoax"
    # 60 minutes: TurnBackHoax's feed holds only the 10 newest articles and
    # they publish roughly 5-15 a day, so an hourly poll cannot miss one
    # between runs while still costing 24 requests a day in the steady state.
    fact_ingestion_interval_minutes: int = 60
    # Upper bound on articles considered per run. The feed carries 10; the
    # cap is what keeps a source that suddenly paginates from turning one
    # scheduled task into an unbounded crawl.
    fact_ingestion_max_items: int = 25
    fact_ingestion_request_timeout_seconds: float = 15.0
    # Minimum gap between two requests to the same source. Politeness, not
    # performance: nothing here is on a user-facing latency budget.
    fact_ingestion_request_delay_seconds: float = 1.5
    fact_ingestion_max_attempts: int = 3
    fact_ingestion_retry_backoff_seconds: float = 2.0
    # Fact-check organisations do edit articles after publishing (a correction,
    # a stronger ruling). An item already stored is therefore re-read — but at
    # most once every `refresh_after_hours`, and only while it is younger than
    # `refresh_window_days`, so the crawl stays roughly one extra request per
    # article per day instead of re-downloading the feed's whole contents every
    # hour. 0 hours disables re-checking entirely.
    fact_ingestion_refresh_after_hours: int = 24
    fact_ingestion_refresh_window_days: int = 7
    # Identify the crawler and give the source's operators a way to reach us —
    # the reason a fact-check organisation tolerates being polled at all.
    fact_ingestion_user_agent: str = "JAWARA-FactCheckBot/1.0 (+https://github.com/dendik-creation)"
    # Push newly ingested items through the existing knowledge sync (ML
    # Service → Qdrant) at the end of a run. False leaves them in PostgreSQL
    # for an operator to review and sync by hand.
    fact_ingestion_auto_sync: bool = True
    turnbackhoax_feed_url: str = "https://turnbackhoax.id/feed"

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
    # Claim extraction sits in front of retrieval, so its cost is added to the
    # pipeline before any evidence is read — kept just above ml-service's own
    # claim_extraction_timeout_seconds so the service's fallback to the
    # deterministic heuristic wins the race against the client giving up.
    ml_timeout_extract_claim_seconds: float = 7.0
    ml_timeout_generate_seconds: float = 8.0
    # train/evaluate run a scikit-learn fit/predict over the whole dataset in
    # ml-service (classifier.py, offloaded to a thread there so it no longer
    # blocks that process's single event loop) — not bounded by the <3.0s
    # pipeline budget above, since these run in the celery training/evaluation
    # queues, not the message pipeline. Sized for real-world sample counts
    # (tens of thousands of rows, full-length article text), not just the
    # tiny seed_dataset_samples fixture — 60s measured as too tight against
    # the actual indonesia_hoax_news corpus even with bounded TF-IDF vocab.
    ml_timeout_train_seconds: float = 300.0
    ml_timeout_evaluate_seconds: float = 120.0
    ml_enabled: bool = True

    # RAG retrieval contract, fixed by 03_Database/02_VectorDB_Specifications.md.
    rag_top_k: int = 3
    rag_score_threshold: float = 0.80
    # Canonicalise the message into a claim before retrieving. A forwarded
    # WhatsApp text and a curated knowledge-base claim describe the same hoax
    # in very different words, and the embedder scores the wrapper too. False
    # sends the raw message straight to `rag-query`, the pre-Phase-2
    # behaviour. Re-ranking weights themselves live in ml-service, which is
    # where the ranking happens.
    rag_claim_extraction_enabled: bool = True

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
        # Compose passes the crawler's User-Agent through with an empty
        # fallback (a default containing spaces and parentheses is awkward to
        # express there). An anonymous crawler is worse than a verbose one, so
        # blank means "use the built-in identifier", never "send nothing".
        if not self.fact_ingestion_user_agent.strip():
            self.fact_ingestion_user_agent = type(self).model_fields["fact_ingestion_user_agent"].default
        return self

    @property
    def fact_ingestion_source_list(self) -> list[str]:
        return [slug.strip() for slug in self.fact_ingestion_sources.split(",") if slug.strip()]

    @property
    def bot_whatsapp_id_list(self) -> list[str]:
        return [jid.strip() for jid in self.bot_whatsapp_ids.split(",") if jid.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
