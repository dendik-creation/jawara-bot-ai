"""Anthropic Messages API provider — the chosen production LLM.

Decision (recorded in `02_Architecture/03_Tech_Stack.md` §4): Claude Haiku. The
vault previously left "OpenAI GPT-4o-mini / Claude Haiku" open, which blocked
[[Generate LLM Responses]]. Reasons for Haiku, in order of weight for this
product:

1. Instruction adherence on a rigid output contract. The reply must contain four
   sections, in order, with every forwardable line prefixed `>`. Fewer repair
   fallbacks means fewer template-flavoured replies reaching users.
2. Indonesian fluency at the polite, non-technical register the persona needs.
3. Latency and cost inside the <3.0s end-to-end budget for a per-message call.

The contract stays provider-agnostic: switching to `LLM_PROVIDER=openai_compatible`
is a config change, and nothing outside this package knows which vendor answered.
"""

import httpx

from app.core.config import Settings
from app.core.errors import MlError
from app.llm.base import LlmProvider
from app.llm.prompt import GenerationRequest, build_user_message, load_system_prompt


class AnthropicProvider(LlmProvider):
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self.version = settings.llm_model
        self._settings = settings

    async def generate(self, request: GenerationRequest) -> str:
        body = {
            "model": self._settings.llm_model,
            "max_tokens": self._settings.llm_max_tokens,
            "temperature": self._settings.llm_temperature,
            # System prompt goes in the dedicated field, never concatenated into
            # the user turn — that separation is what keeps retrieved knowledge
            # from being read as instructions.
            "system": load_system_prompt(),
            "messages": [{"role": "user", "content": build_user_message(request)}],
        }

        try:
            async with httpx.AsyncClient(timeout=self._settings.llm_timeout_seconds) as client:
                response = await client.post(
                    f"{self._settings.anthropic_base_url.rstrip('/')}/messages",
                    headers={
                        "x-api-key": self._settings.anthropic_api_key,
                        "anthropic-version": self._settings.anthropic_version,
                        "content-type": "application/json",
                    },
                    json=body,
                )
        except httpx.TimeoutException as exc:
            # Not retryable from the caller's perspective: generation is the one
            # endpoint that must fall back rather than be retried blindly.
            raise MlError("llm_timeout", str(exc), status_code=504, retryable=False) from exc
        except httpx.HTTPError as exc:
            raise MlError("llm_unreachable", type(exc).__name__, status_code=502, retryable=False) from exc

        if response.status_code == 429:
            raise MlError("llm_rate_limited", "provider rate limit", status_code=429, retryable=False)
        if response.status_code >= 400:
            raise MlError(
                "llm_provider_error", f"HTTP {response.status_code}", status_code=502, retryable=False
            )

        blocks = response.json().get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not text.strip():
            raise MlError("llm_empty_response", "provider returned no text", status_code=502, retryable=False)
        return text
