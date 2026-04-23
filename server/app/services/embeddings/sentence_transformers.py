"""Sentence-Transformers embedding provider (local, no API key needed)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from app.services.embeddings.base import EmbeddingProvider

if TYPE_CHECKING:
    pass


class SentenceTransformersProvider(EmbeddingProvider):
    """Embedding provider using sentence-transformers (runs locally in a thread pool)."""

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model
        self._encoder = None  # lazy-loaded

    def _get_encoder(self):
        if self._encoder is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers is not installed. "
                    "Install it with: pip install sentence-transformers"
                ) from exc
            logger.info(f"Loading sentence-transformers model: {self._model_name}")
            self._encoder = SentenceTransformer(self._model_name)
        return self._encoder

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int | None:
        return None

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        loop = asyncio.get_event_loop()
        encoder = self._get_encoder()
        vector = await loop.run_in_executor(
            None, lambda: encoder.encode(text, normalize_embeddings=True).tolist()
        )
        return vector, len(vector)

    async def generate_embeddings_batch(self, texts: list[str]) -> list[tuple[list[float], int]]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        encoder = self._get_encoder()
        vectors = await loop.run_in_executor(
            None,
            lambda: encoder.encode(texts, normalize_embeddings=True).tolist(),
        )
        return [(v, len(v)) for v in vectors]
