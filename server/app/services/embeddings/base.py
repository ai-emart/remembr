"""Abstract base class for embedding providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Provider-agnostic interface for text embedding generation."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Model identifier string."""

    @property
    @abstractmethod
    def dimensions(self) -> int | None:
        """Output vector dimensions, or None if dynamic."""

    @abstractmethod
    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        """Return (vector, dimensions) for a single text."""

    @abstractmethod
    async def generate_embeddings_batch(self, texts: list[str]) -> list[tuple[list[float], int]]:
        """Return list of (vector, dimensions) for multiple texts."""
