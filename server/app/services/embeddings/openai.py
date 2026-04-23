"""OpenAI embedding provider."""

from __future__ import annotations

from loguru import logger

from app.services.embeddings.base import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by the OpenAI embeddings API."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        self._api_key = api_key
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int | None:
        return None

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        results = await self.generate_embeddings_batch([text])
        return results[0]

    async def generate_embeddings_batch(self, texts: list[str]) -> list[tuple[list[float], int]]:
        if not texts:
            return []
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "openai package is not installed. Install it with: pip install openai"
            ) from exc

        client = AsyncOpenAI(api_key=self._api_key)
        response = await client.embeddings.create(model=self._model, input=texts)
        logger.debug(f"OpenAI: generated {len(response.data)} embeddings")
        return [
            (item.embedding, len(item.embedding))
            for item in sorted(response.data, key=lambda x: x.index)
        ]
