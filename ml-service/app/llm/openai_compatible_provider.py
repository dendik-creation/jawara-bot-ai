"""OpenAI-compatible Chat Completions provider.

Not "OpenAI the vendor" specifically — any endpoint that speaks the same
`POST {base_url}/chat/completions` wire format (official OpenAI, OpenRouter,
Groq, a self-hosted vLLM/Ollama, ...). `LLM_BASE_URL`/`LLM_API_KEY`/
`LLM_MODEL` name exactly which one, kept separate from the embedding
provider's own `OPENAI_API_KEY`/`OPENAI_BASE_URL` — unrelated services that
happen to share a vendor name.
"""

import httpx

from app.core.config import Settings
from app.core.errors import MlError
from app.llm.base import LlmProvider
from app.llm.prompt import GenerationRequest, build_user_message, load_system_prompt


class OpenAICompatibleProvider(LlmProvider):
    name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        self.version = settings.llm_model
        self._settings = settings

    async def generate(self, request: GenerationRequest) -> str:
        body = {
            "model": self._settings.llm_model,
            "max_tokens": self._settings.llm_max_tokens,
            "temperature": self._settings.llm_temperature,
            "messages": [
                {"role": "system", "content": load_system_prompt()},
                {"role": "user", "content": build_user_message(request)},
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                response = await client.post(
                    f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise MlError("llm_timeout", str(exc), status_code=504, retryable=False) from exc
        except httpx.HTTPError as exc:
            raise MlError("llm_unreachable", type(exc).__name__, status_code=502, retryable=False) from exc

        if response.status_code == 429:
            raise MlError("llm_rate_limited", "provider rate limit", status_code=429, retryable=False)
        if response.status_code >= 400:
            raise MlError(
                "llm_provider_error", f"HTTP {response.status_code}", status_code=502, retryable=False
            )

        choices = response.json().get("choices") or []
        text = (choices[0].get("message", {}).get("content") if choices else "") or ""
        if not text.strip():
            raise MlError("llm_empty_response", "provider returned no text", status_code=502, retryable=False)
        return text
