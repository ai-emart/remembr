"""Ollama local embedding provider."""

from __future__ import annotations

import httpx
from loguru import logger

from app.services.embeddings.base import EmbeddingProvider


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by a local Ollama instance."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int | None:
        return None

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            if response.status_code != 200:
                raise ValueError(f"Ollama error {response.status_code}: {response.text}")
            vector: list[float] = response.json()["embedding"]
            logger.debug(f"Ollama embedding generated, dims={len(vector)}")
            return vector, len(vector)

    async def generate_embeddings_batch(
        self, texts: list[str]
    ) -> list[tuple[list[float], int]]:
        results = []
        for text in texts:
            results.append(await self.generate_embedding(text))
        return results
