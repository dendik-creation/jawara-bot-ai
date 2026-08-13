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

    # Re-ranking (app/rag/ranking.py). Retrieval asks Qdrant for
    # `top_k * overfetch` candidates and returns the best `top_k` after
    # weighting by source reliability and freshness — reordering only, never
    # re-filtering, so `score` stays the documented cosine similarity.
    rag_rerank_enabled: bool = True
    # 3x: enough headroom for a trustworthy fourth match to overtake a shaky
    # second, without turning every query into a wide scan.
    rag_rerank_overfetch: int = 3
    # Both weights are the maximum penalty their signal may apply. 0 disables
    # that signal exactly; 1.0 would let a zero-reliability or infinitely old
    # match be scored to zero. Reliability is weighted higher than recency:
    # who said it is a stronger signal than when, and a two-year-old MAFINDO
    # debunk of a recirculating hoax is still the right answer.
    rag_reliability_weight: float = 0.4
    rag_recency_weight: float = 0.25
    # Days at which the recency factor halves. 180 ≈ two turns of the seasonal
    # hoax cycle — long enough that a genuinely useful old debunk survives.
    rag_recency_half_life_days: float = 180.0

    # --- Claim extraction (app/rag/claim.py) -------------------------------
    # "auto" uses the LLM when one is actually configured and the deterministic
    # heuristic otherwise; "llm"/"heuristic" force one path. The heuristic is
    # not a stub — it is what runs offline, in CI, and whenever the vendor
    # fails mid-request.
    claim_extraction_provider: str = "auto"
    # Messages shorter than this are already claims; rewriting them into
    # themselves would spend an LLM round trip out of the <3s budget for
    # nothing.
    claim_extraction_min_input_chars: int = 180
    claim_extraction_max_chars: int = 320
    claim_extraction_max_tokens: int = 200
    # Tighter than llm_timeout_seconds: this call sits in front of retrieval,
    # so its whole cost is added to the pipeline before any evidence is read.
    claim_extraction_timeout_seconds: float = 6.0

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
    # Reasoning-capable models (e.g. Gemini 2.5+/3.x) spend part of max_tokens on
    # invisible thinking tokens before the visible completion — a budget sized
    # for the ~150-300 word four-section reply alone gets exhausted by thinking
    # first and truncates (finish_reason=length) before any visible text lands.
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 20.0
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_version: str = "2023-06-01"
    # Path up to and including `/v1` — the provider appends `/chat/completions`.
    llm_base_url: str = ""
    llm_api_key: str = ""

    # --- OCR (app/models/ocr.py) -------------------------------------------
    # Self-hosted, CPU-only, no external API dependency — matches the
    # offline-by-default posture the rest of this service already takes
    # (hash embedder, template LLM composer). "tesseract" is the only
    # provider implemented; the OCRProvider interface exists so a second one
    # is a new class registered in registry.py, not a rewrite of the
    # endpoint.
    ocr_provider: str = "tesseract"
    # Tesseract's own `+`-joined language list — Indonesian first, since most
    # traffic is Indonesian WhatsApp forwards.
    ocr_languages: str = "ind+eng"
    ocr_max_image_size_mb: float = 10.0
    ocr_max_width: int = 4096
    ocr_max_height: int = 4096
    # Wall-clock budget for one OCR call, including the bounded retry below.
    # asyncio.wait_for at the endpoint enforces this even if pytesseract's own
    # subprocess call hangs.
    ocr_timeout_seconds: float = 15.0
    ocr_max_text_length: int = 10000
    # Below this the endpoint attempts exactly one retry with heavier
    # preprocessing (grayscale + autocontrast) before giving up on a better
    # reading. Deliberately lower than the gateway's OCR_MIN_CONFIDENCE (the
    # accept/flag line) — this is "worth trying again", not "good enough to
    # trust".
    ocr_retry_confidence_threshold: float = 0.35

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
