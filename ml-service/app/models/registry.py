"""Model registry — `name+version → loaded instance`, built once at startup.

Multi-model from day one (02_Architecture/04_ML_Service.md §7): adding a second
embedder or a second LLM is an entry here plus a config value, not a rewrite.
Loading happens in the lifespan hook, never per request, which is also what
makes readiness meaningfully different from liveness (§6).
"""

import logging
from pathlib import Path

from app.core.config import Settings
from app.embeddings.base import Embedder
from app.embeddings.hashing import HashingEmbedder
from app.embeddings.openai import OpenAIEmbedder
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LlmProvider
from app.llm.openai_compatible_provider import OpenAICompatibleProvider
from app.llm.template_provider import TemplateProvider
from app.models import classifier as classifier_module

logger = logging.getLogger("app.models.registry")


class ModelRegistry:
    def __init__(self) -> None:
        self._embedders: dict[str, Embedder] = {}
        self._llms: dict[str, LlmProvider] = {}
        # Keyed by (model_version, expected_sha256) — see `classifier()`.
        self._classifiers: dict[tuple[str, str], classifier_module.TrainedClassifier] = {}
        self.active_embedder: str = ""
        self.active_llm: str = ""
        self.loaded = False
        self.degraded_reasons: list[str] = []
        self._artifact_dir: Path = Path("model_artifacts")

    def load(self, settings: Settings) -> None:
        """Build every configured model. Idempotent."""
        embedder = self._build_embedder(settings)
        self._embedders[embedder.model_version] = embedder
        self.active_embedder = embedder.model_version

        llm = self._build_llm(settings)
        self._llms[llm.model_version] = llm
        self.active_llm = llm.model_version

        # Classifiers are not preloaded — which versions exist is driven by
        # the gateway's training jobs, not by static config, so they are
        # loaded lazily on first use (see `classifier()` below).
        self._artifact_dir = Path(settings.model_artifact_dir)

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
        if provider == "openai_compatible":
            if not settings.llm_base_url or not settings.llm_api_key:
                self.degraded_reasons.append("llm_openai_compatible_config_missing")
                logger.warning("LLM_BASE_URL/LLM_API_KEY missing, falling back to template composer")
                return TemplateProvider()
            return OpenAICompatibleProvider(settings)
        return TemplateProvider()

    def embedder(self, model_version: str | None = None) -> Embedder:
        return self._embedders[model_version or self.active_embedder]

    def llm(self, model_version: str | None = None) -> LlmProvider:
        return self._llms[model_version or self.active_llm]

    def classifier(self, model_version: str, expected_sha256: str) -> classifier_module.TrainedClassifier:
        """Load-and-cache, or raise. Never returns an artifact whose checksum
        doesn't match `expected_sha256` (07_Model_Registry_and_Deployment §7).

        Cache key includes the checksum, not just `model_version` — caching
        on `model_version` alone would let a caller who once supplied the
        right checksum skip verification on every later call, including one
        that (by bug or bad data) supplies a wrong checksum for a version
        already sitting in the cache.
        """
        cache_key = (model_version, expected_sha256)
        cached = self._classifiers.get(cache_key)
        if cached is not None:
            return cached

        path = self._artifact_dir / f"{model_version}.joblib"
        model = classifier_module.load(path, expected_sha256)
        self._classifiers[cache_key] = model
        return model

    def register_classifier(
        self, model_version: str, expected_sha256: str, model: classifier_module.TrainedClassifier
    ) -> None:
        """Cache a freshly trained model immediately, so `/v1/train` followed
        by `/v1/evaluate` in the same process doesn't re-read its own artifact
        off disk a moment after writing it.
        """
        self._classifiers[(model_version, expected_sha256)] = model

    def describe(self) -> dict[str, object]:
        return {
            "loaded": self.loaded,
            "embedder": self.active_embedder,
            "embedders": sorted(self._embedders),
            "llm": self.active_llm,
            "llms": sorted(self._llms),
            "classifiers_loaded": sorted(f"{version}:{sha[:12]}" for version, sha in self._classifiers),
            "degraded_reasons": self.degraded_reasons,
        }


registry = ModelRegistry()
