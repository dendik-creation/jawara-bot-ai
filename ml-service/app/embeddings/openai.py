"""OpenAI embeddings (`text-embedding-3-small`, 1536-dim).

Selected with `EMBEDDING_PROVIDER=openai`. The model name and dimension both
come from config so a move to IndoBERT (768) is a config + collection rebuild,
not a code change.
"""

import httpx

from app.core.errors import MlError
from app.embeddings.base import Embedder


class OpenAIEmbedder(Embedder):
    name = "openai-embed"

    def __init__(self, dim: int, api_key: str, model: str, base_url: str, timeout: float) -> None:
        super().__init__(dim)
        self.version = model
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "input": texts},
                )
        except httpx.TimeoutException as exc:
            raise MlError("embedding_timeout", str(exc), status_code=504, retryable=True) from exc
        except httpx.HTTPError as exc:
            raise MlError("embedding_unreachable", type(exc).__name__, status_code=502, retryable=True) from exc

        if response.status_code == 429:
            raise MlError("embedding_rate_limited", "provider rate limit", status_code=429, retryable=True)
        if response.status_code >= 400:
            raise MlError(
                "embedding_provider_error",
                f"HTTP {response.status_code}",
                status_code=502,
                retryable=response.status_code >= 500,
            )

        data = response.json().get("data") or []
        # The API returns results with an explicit index; sorting by it rather
        # than trusting array order keeps vectors aligned with their inputs.
        vectors = [item["embedding"] for item in sorted(data, key=lambda item: item.get("index", 0))]
        self.ensure_dimension(vectors)
        return vectors
