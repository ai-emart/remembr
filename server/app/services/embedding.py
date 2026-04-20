"""Embedding generation service using Jina AI API."""

import asyncio
from typing import Literal

import httpx
from loguru import logger

from app.config import get_settings


class EmbeddingService:
    """
    Service for generating embeddings using Jina AI API.

    Supports both single and batch embedding generation with automatic
    retry logic for rate limits and transient errors.
    """

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.jina_api_key.get_secret_value()
        self.model = self.settings.jina_embedding_model
        self.base_url = "https://api.jina.ai/v1/embeddings"
        self.batch_size = getattr(self.settings, "embedding_batch_size", 100)
        self.max_retries = 3

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        """
        Generate embedding for a single text.

        Returns:
            Tuple of (embedding vector, dimensions)
        """
        vectors = await self._request_with_retry([text], timeout=30.0)
        vector = vectors[0]
        return vector, len(vector)

    async def generate_embeddings_batch(self, texts: list[str]) -> list[tuple[list[float], int]]:
        """
        Generate embeddings for multiple texts.

        Automatically splits requests larger than 2048 items.

        Returns:
            List of (embedding vector, dimensions) tuples
        """
        if not texts:
            return []

        if len(texts) > 2048:
            logger.warning(
                f"Batch size {len(texts)} exceeds Jina limit of 2048, "
                "splitting into multiple requests"
            )
            all_results: list[tuple[list[float], int]] = []
            for i in range(0, len(texts), 2048):
                chunk = texts[i : i + 2048]
                all_results.extend(await self.generate_embeddings_batch(chunk))
            return all_results

        vectors = await self._request_with_retry(texts, timeout=60.0)
        return [(v, len(v)) for v in vectors]

    async def _request_with_retry(
        self,
        texts: list[str],
        timeout: float,
        task: Literal["retrieval.passage", "retrieval.query"] = "retrieval.passage",
    ) -> list[list[float]]:
        """Make API request with exponential backoff retry on 429 and 5xx."""
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        self.base_url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "task": task,
                            "input": texts,
                        },
                    )

                    if response.status_code == 200:
                        data = response.json()
                        embeddings = [item["embedding"] for item in data["data"]]
                        logger.debug(
                            f"Generated {len(embeddings)} embeddings "
                            f"(task={task}, model={self.model})"
                        )
                        return embeddings

                    elif response.status_code == 429:
                        wait_time = 2**attempt
                        logger.warning(
                            f"Rate limit hit, retrying in {wait_time}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    elif response.status_code >= 500:
                        wait_time = 2**attempt
                        logger.warning(
                            f"Server error {response.status_code}, "
                            f"retrying in {wait_time}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        continue

                    else:
                        logger.error(f"Jina API error {response.status_code}: {response.text}")
                        raise ValueError(f"Jina API error {response.status_code}: {response.text}")

            except httpx.TimeoutException:
                wait_time = 2**attempt
                logger.warning(
                    f"Request timeout, retrying in {wait_time}s "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )
                await asyncio.sleep(wait_time)
                continue

            except httpx.RequestError as e:
                logger.error(f"Request error: {e}")
                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)
                    continue
                raise

        raise RuntimeError(f"Failed to generate embeddings after {self.max_retries} attempts")

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(a) != len(b):
            raise ValueError("Vectors must have the same length")

        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = sum(x * x for x in a) ** 0.5
        magnitude_b = sum(x * x for x in b) ** 0.5

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)
