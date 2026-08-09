"""Model registry — `name+version → loaded instance`, built once at startup.

Multi-model from day one (02_Architecture/04_ML_Service.md §7): adding a second
embedder or a second LLM is an entry here plus a config value, not a rewrite.
Loading happens in the lifespan hook, never per request, which is also what
makes readiness meaningfully different from liveness (§6).
"""

import logging

from app.core.config import Settings
from app.embeddings.base import Embedder
from app.embeddings.hashing import HashingEmbedder
from app.embeddings.openai import OpenAIEmbedder
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LlmProvider
from app.llm.openai_provider import OpenAIChatProvider
from app.llm.template_provider import TemplateProvider

logger = logging.getLogger("app.models.registry")


class ModelRegistry:
    def __init__(self) -> None:
        self._embedders: dict[str, Embedder] = {}
        self._llms: dict[str, LlmProvider] = {}
        self.active_embedder: str = ""
        self.active_llm: str = ""
        self.loaded = False
        self.degraded_reasons: list[str] = []

    def load(self, settings: Settings) -> None:
        """Build every configured model. Idempotent."""
        embedder = self._build_embedder(settings)
        self._embedders[embedder.model_version] = embedder
        self.active_embedder = embedder.model_version

        llm = self._build_llm(settings)
        self._llms[llm.model_version] = llm
        self.active_llm = llm.model_version

        self.loaded = True
        logger.info(
            "models loaded",
            extra={
                "embedder": self.active_embedder,
                "llm": self.active_llm,
                "degraded": self.degraded_reasons,
            },
        )

    def _build_embedder(self, settings: Settings) -> Embedder:
        if settings.embedding_provider == "openai":
            if not settings.openai_api_key:
                self.degraded_reasons.append("openai_embedding_key_missing")
                logger.warning("OPENAI_API_KEY missing, falling back to hash embedder")
                return HashingEmbedder(settings.embedding_dim)
            return OpenAIEmbedder(
                dim=settings.embedding_dim,
                api_key=settings.openai_api_key,
                model=settings.embedding_model,
                base_url=settings.openai_base_url,
                timeout=settings.embedding_timeout_seconds,
            )
        return HashingEmbedder(settings.embedding_dim)

    def _build_llm(self, settings: Settings) -> LlmProvider:
        provider = settings.llm_provider.lower()
        if provider == "anthropic":
            if not settings.anthropic_api_key:
                self.degraded_reasons.append("anthropic_key_missing")
                logger.warning("ANTHROPIC_API_KEY missing, falling back to template composer")
                return TemplateProvider()
            return AnthropicProvider(settings)
        if provider == "openai":
            if not settings.openai_api_key:
                self.degraded_reasons.append("openai_key_missing")
                logger.warning("OPENAI_API_KEY missing, falling back to template composer")
                return TemplateProvider()
            return OpenAIChatProvider(settings)
        return TemplateProvider()

    def embedder(self, model_version: str | None = None) -> Embedder:
        return self._embedders[model_version or self.active_embedder]

    def llm(self, model_version: str | None = None) -> LlmProvider:
        return self._llms[model_version or self.active_llm]

    def describe(self) -> dict[str, object]:
        return {
            "loaded": self.loaded,
            "embedder": self.active_embedder,
            "embedders": sorted(self._embedders),
            "llm": self.active_llm,
            "llms": sorted(self._llms),
            "degraded_reasons": self.degraded_reasons,
        }


registry = ModelRegistry()
