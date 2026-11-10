"""Text embeddings for pgvector.

Default is a local ONNX model (fastembed, BAAI/bge-small-en-v1.5, 384-d): free, no API key, ~30ms per
document on CPU. The "hash" backend is a deterministic bag-of-words projection used in tests and as a
fallback if the model cannot be loaded (e.g. no network on first boot).
"""

import asyncio
import hashlib
import math
import re
from functools import lru_cache

from app.config import settings
from app.logging import log

_TOKEN = re.compile(r"[a-z0-9+#]+")


def _hash_embed(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    tokens = _TOKEN.findall(text.lower())
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    for g in grams:
        h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "little")
        vec[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class Embedder:
    def __init__(self) -> None:
        self.dim = settings.embedding_dim
        self.backend = settings.embedding_backend
        self._model = None
        if self.backend == "fastembed":
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(model_name=settings.embedding_model)
            except Exception as exc:  # model download / onnxruntime failure
                log.warning("embeddings.fallback_to_hash", error=str(exc))
                self.backend = "hash"

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            return [_hash_embed(t, self.dim) for t in texts]
        return [v.tolist() for v in self._model.embed(texts, batch_size=32)]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Truncate: bge-small has a 512-token window; the head of a posting carries the signal.
        clipped = [t[:4000] for t in texts]
        return await asyncio.to_thread(self._embed_sync, clipped)

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    def to_score(self, similarity: float) -> float:
        """Map raw cosine similarity onto 0-100. Ranges are calibrated per backend on the eval set
        (bge-small puts unrelated postings around 0.6 and close fits above 0.8)."""
        lo, hi = self._range()
        return max(0.0, min(100.0, 100.0 * (similarity - lo) / (hi - lo)))

    def max_distance(self, score: float) -> float:
        """Inverse of to_score as a pgvector cosine distance: jobs closer than this score at least `score`."""
        lo, hi = self._range()
        return 1.0 - (lo + (hi - lo) * score / 100.0)

    def _range(self) -> tuple[float, float]:
        return (0.60, 0.82) if self.backend == "fastembed" else (0.05, 0.40)


@lru_cache
def get_embedder() -> Embedder:
    return Embedder()


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
