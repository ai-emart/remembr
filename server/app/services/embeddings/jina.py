"""Jina AI embedding provider."""

from __future__ import annotations

import asyncio
from typing import Literal

import httpx
from loguru import logger

from app.services.embeddings.base import EmbeddingProvider


class JinaEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by the Jina AI API."""

    def __init__(self, api_key: str, model: str = "jina-embeddings-v3") -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = "https://api.jina.ai/v1/embeddings"
        self._max_retries = 3

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int | None:
        return None

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        vectors = await self._request_with_retry([text], timeout=30.0)
        vector = vectors[0]
        return vector, len(vector)

    async def generate_embeddings_batch(
        self, texts: list[str]
    ) -> list[tuple[list[float], int]]:
        if not texts:
            return []
        if len(texts) > 2048:
            logger.warning(f"Batch size {len(texts)} exceeds Jina limit of 2048, splitting")
            results: list[tuple[list[float], int]] = []
            for i in range(0, len(texts), 2048):
                results.extend(await self.generate_embeddings_batch(texts[i : i + 2048]))
            return results
        vectors = await self._request_with_retry(texts, timeout=60.0)
        return [(v, len(v)) for v in vectors]

    async def _request_with_retry(
        self,
        texts: list[str],
        timeout: float,
        task: Literal["retrieval.passage", "retrieval.query"] = "retrieval.passage",
    ) -> list[list[float]]:
        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        self._base_url,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={"model": self._model, "task": task, "input": texts},
                    )

                    if response.status_code == 200:
                        data = response.json()
                        return [item["embedding"] for item in data["data"]]

                    elif response.status_code == 429:
                        wait = 2**attempt
                        logger.warning(f"Jina rate limit, retrying in {wait}s")
                        await asyncio.sleep(wait)

                    elif response.status_code >= 500:
                        wait = 2**attempt
                        logger.warning(
                            f"Jina server error {response.status_code}, retrying in {wait}s"
                        )
                        await asyncio.sleep(wait)

                    else:
                        raise ValueError(f"Jina API error {response.status_code}: {response.text}")

            except httpx.TimeoutException:
                wait = 2**attempt
                logger.warning(f"Jina request timeout, retrying in {wait}s")
                await asyncio.sleep(wait)

            except httpx.RequestError as e:
                logger.error(f"Jina request error: {e}")
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                raise

        raise RuntimeError(f"Jina: failed after {self._max_retries} attempts")
