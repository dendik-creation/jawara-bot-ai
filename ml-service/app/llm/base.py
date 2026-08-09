"""LLM provider interface.

Provider choice is an internal detail of ML Service. The gateway calls
`POST /v1/generate` and gets back a validated four-section message; whether that
came from Anthropic, OpenAI, or the offline composer is visible only as
`model_version` in the response and the audit row.
"""

from abc import ABC, abstractmethod

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
