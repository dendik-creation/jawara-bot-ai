"""Embedder interface.

Provider-agnostic on purpose: the vector dimension is configuration
(`EMBEDDING_DIM`: 1536 for `text-embedding-3-small`, 768 for IndoBERT), and
Qdrant cannot change a collection's dimension in place. Swapping the embedder
therefore means recreating the collection and re-embedding the knowledge base —
`ensure_dimension` exists so that mistake fails loudly at startup instead of
silently at the first upsert.
"""

from abc import ABC, abstractmethod


class Embedder(ABC):
    name: str = "embedder"
    version: str = "v0"

    def __init__(self, dim: int) -> None:
        self.dim = dim

    @property
    def model_version(self) -> str:
        return f"{self.name}-{self.version}"

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, one vector per input, in input order."""

    def ensure_dimension(self, vectors: list[list[float]]) -> None:
        for vector in vectors:
            if len(vector) != self.dim:
                raise ValueError(
                    f"{self.model_version} produced a {len(vector)}-dim vector, "
                    f"collection expects {self.dim}"
                )
