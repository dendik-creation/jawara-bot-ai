"""OpenAI Chat Completions provider — the documented alternative.

Kept implemented, not just mentioned, so the "provider-agnostic contract" claim
in `04_ML_Service.md` §4 is demonstrable: `LLM_PROVIDER=openai` swaps the vendor
with no change above this package.
"""

import httpx

from app.core.config import Settings
from app.core.errors import MlError
from app.llm.base import LlmProvider
from app.llm.prompt import GenerationRequest, build_user_message, load_system_prompt


class OpenAIChatProvider(LlmProvider):
    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.version = settings.openai_chat_model
        self._settings = settings

    async def generate(self, request: GenerationRequest) -> str:
        body = {
            "model": self._settings.openai_chat_model,
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
                    f"{self._settings.openai_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self._settings.openai_api_key}"},
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
