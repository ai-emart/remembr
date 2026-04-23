"""Thin shim — delegates to the active embedding provider from the embeddings package.

Kept for backwards compatibility with callers that imported EmbeddingService directly.
"""

from __future__ import annotations

from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.factory import get_embedding_provider


class EmbeddingService:
    """Backwards-compatible wrapper around the active EmbeddingProvider."""

    def __init__(self) -> None:
        self._provider: EmbeddingProvider = get_embedding_provider()

    @property
    def model(self) -> str:
        return self._provider.model

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        return await self._provider.generate_embedding(text)

    async def generate_embeddings_batch(self, texts: list[str]) -> list[tuple[list[float], int]]:
        return await self._provider.generate_embeddings_batch(texts)

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            raise ValueError("Vectors must have the same length")
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = sum(x * x for x in a) ** 0.5
        mag_b = sum(x * x for x in b) ** 0.5
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
