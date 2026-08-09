"""Deterministic offline embedder — the default when no provider key is set.

What it is: a hashed bag of word unigrams, word bigrams, and character 4-grams,
projected into `EMBEDDING_DIM` and L2-normalised. Cosine similarity over these
vectors is a *lexical* overlap measure — it matches "daun kitolod katarak"
against a fact item about daun kitolod, and it does not understand paraphrase.

What it is not: a semantic model. It exists so the whole RAG path — collection
config, filters, thresholds, unverified handling, prompt assembly — is real,
runnable and testable without an API key or a GPU, and so CI never depends on a
third party. Switching `EMBEDDING_PROVIDER=openai` swaps in real semantics
without touching a single caller.

Because the signal is lexical, the documented 0.80 threshold behaves more
strictly here than it would with `text-embedding-3-small`: near-duplicate
wording matches, loose paraphrase does not. That is the honest failure mode —
"Unverified" rather than a confident wrong answer.
"""

import hashlib
import math
import re

from app.embeddings.base import Embedder

_TOKEN = re.compile(r"[a-z0-9]+")
_CHAR_NGRAM = 4


def _hash_index(token: str, dim: int) -> tuple[int, float]:
    """Stable bucket + sign for a token.

    blake2b, not `hash()`: Python's string hashing is randomised per process, so
    `hash()` would produce a different embedding on every restart and silently
    invalidate everything already stored in Qdrant.
    """
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    # Signed hashing: opposite signs let unrelated tokens cancel instead of
    # always adding, which keeps collisions from inflating similarity.
    sign = 1.0 if value & 1 else -1.0
    return value % dim, sign


class HashingEmbedder(Embedder):
    name = "hash-embed"
    version = "v0"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = _TOKEN.findall((text or "").casefold())

        for token in tokens:
            index, sign = _hash_index(f"w:{token}", self.dim)
            vector[index] += sign

        for left, right in zip(tokens, tokens[1:]):
            index, sign = _hash_index(f"b:{left}_{right}", self.dim)
            vector[index] += sign * 0.8

        joined = " ".join(tokens)
        for start in range(max(0, len(joined) - _CHAR_NGRAM + 1)):
            gram = joined[start : start + _CHAR_NGRAM]
            index, sign = _hash_index(f"c:{gram}", self.dim)
            vector[index] += sign * 0.35

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # Qdrant rejects a zero vector under cosine distance; a single fixed
            # unit component keeps empty input representable and similar only to
            # other empty input.
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]
