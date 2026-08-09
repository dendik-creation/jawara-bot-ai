from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    llm_provider: str = "template"
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_max_tokens: int = 900
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 20.0
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_version: str = "2023-06-01"
    openai_chat_model: str = "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()
