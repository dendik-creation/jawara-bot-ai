from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # protected_namespaces=(): pydantic reserves the `model_` prefix for its
    # own internals by default, which would warn on `model_artifact_dir`.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    # Service-to-service auth. The gateway sends this as X-Internal-Api-Key;
    # ML Service is never exposed outside the Docker network
    # (09_Security/06_Platform_Security_Requirements §1).
    ml_service_api_key: str = "changeme"
    port: int = 9000
    log_level: str = "INFO"

    # --- Vector store -----------------------------------------------------
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "fact_knowledge_base"
    qdrant_timeout_seconds: int = 5

    # --- Embeddings -------------------------------------------------------
    # "hash"   — deterministic offline embedder, no API key, dev/CI default
    # "openai" — text-embedding-3-small (1536-dim)
    embedding_provider: str = "hash"
    embedding_dim: int = 1536
    embedding_model: str = "text-embedding-3-small"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    embedding_timeout_seconds: float = 10.0

    # --- Retrieval --------------------------------------------------------
    rag_top_k: int = 3
    rag_score_threshold: float = 0.80

    # --- LLM --------------------------------------------------------------
    # Decision (03_Tech_Stack §4): Anthropic Claude Haiku is the production
    # provider. "template" is the deterministic offline composer used when no
    # key is configured — it produces the same four-section contract without a
    # network call, so CI and offline demos never depend on a vendor.
    # "openai_compatible" is any Chat Completions API that speaks the same
    # wire format as OpenAI's — official OpenAI, OpenRouter, Groq, a
    # self-hosted vLLM/Ollama endpoint, etc — configured entirely through
    # LLM_BASE_URL/LLM_API_KEY/LLM_MODEL, deliberately separate from the
    # embedding provider's own OPENAI_API_KEY/OPENAI_BASE_URL above: the two
    # are unrelated services that happen to share a vendor name.
    llm_provider: str = "template"
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_max_tokens: int = 900
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 20.0
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_version: str = "2023-06-01"
    # Path up to and including `/v1` — the provider appends `/chat/completions`.
    llm_base_url: str = ""
    llm_api_key: str = ""

    # --- Threat classifier --------------------------------------------------
    # Where trained classifier artifacts (`{model_version}.joblib`) live.
    # Mounted on a named volume in docker-compose.yml so training survives a
    # container rebuild — the model registry (Postgres, owned by the gateway)
    # is the source of truth for which version is production; this is just
    # where the bytes it points at are kept.
    model_artifact_dir: str = "/app/model_artifacts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
