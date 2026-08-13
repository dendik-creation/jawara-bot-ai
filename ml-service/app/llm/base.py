"""LLM provider interface.

Provider choice is an internal detail of ML Service. The gateway calls
`POST /v1/generate` and gets back a validated four-section message; whether that
came from Anthropic, OpenAI, or the offline composer is visible only as
`model_version` in the response and the audit row.
"""

from abc import ABC, abstractmethod

from app.core.errors import MlError
from app.llm.prompt import GenerationRequest


class LlmProvider(ABC):
    name: str = "llm"
    version: str = "v0"

    @property
    def model_version(self) -> str:
        return f"{self.name}-{self.version}"

    @property
    def is_offline(self) -> bool:
        """True when the provider needs no network call."""
        return False

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> str:
        """Produce the raw WhatsApp reply text. Validation happens downstream."""

    async def complete(
        self, system: str, user: str, *, max_tokens: int, temperature: float, timeout: float
    ) -> str:
        """One free-form completion, for the service's *other* prompts.

        Claim extraction needs the same transport, auth and error vocabulary as
        reply generation but none of its four-section contract, so the two share
        this call rather than a second HTTP client. Offline providers (the
        template composer) have nothing to complete and say so — callers are
        expected to have a deterministic path of their own.
        """
        raise MlError(
            "llm_offline",
            f"{self.model_version} cannot serve free-form completions",
            status_code=503,
            retryable=False,
        )
