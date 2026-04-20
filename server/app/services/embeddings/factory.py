"""Factory for creating and caching the active embedding provider."""

from __future__ import annotations

from loguru import logger

from app.services.embeddings.base import EmbeddingProvider

_provider_singleton: EmbeddingProvider | None = None
_provider_override: EmbeddingProvider | None = None


class ConfigurationError(Exception):
    """Raised when a required provider configuration is missing."""


def get_embedding_provider() -> EmbeddingProvider:
    """Return the active embedding provider (singleton, lazily constructed)."""
    global _provider_singleton

    if _provider_override is not None:
        return _provider_override

    if _provider_singleton is None:
        _provider_singleton = _create_provider()

    return _provider_singleton


def set_embedding_provider_override(provider: EmbeddingProvider | None) -> None:
    """Override the active provider — use in tests, then reset to None afterwards."""
    global _provider_override
    _provider_override = provider


def _create_provider() -> EmbeddingProvider:
    from app.config import get_settings

    settings = get_settings()
    provider_name: str = getattr(settings, "embedding_provider", "sentence_transformers")

    logger.info(f"Initializing embedding provider: {provider_name}")

    if provider_name == "jina":
        if not settings.jina_api_key:
            raise ConfigurationError("JINA_API_KEY is required when EMBEDDING_PROVIDER=jina")
        from app.services.embeddings.jina import JinaEmbeddingProvider

        return JinaEmbeddingProvider(
            api_key=settings.jina_api_key.get_secret_value(),
            model=getattr(settings, "jina_embedding_model", "jina-embeddings-v3"),
        )

    if provider_name == "ollama":
        from app.services.embeddings.ollama import OllamaEmbeddingProvider

        return OllamaEmbeddingProvider(
            base_url=getattr(settings, "ollama_base_url", "http://localhost:11434"),
            model=getattr(settings, "ollama_embedding_model", "nomic-embed-text"),
        )

    if provider_name == "openai":
        if not settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
        from app.services.embeddings.openai import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            model=getattr(settings, "openai_embedding_model", "text-embedding-3-small"),
        )

    if provider_name == "sentence_transformers":
        from app.services.embeddings.sentence_transformers import SentenceTransformersProvider

        return SentenceTransformersProvider(
            model=getattr(settings, "sentence_transformers_model", "all-MiniLM-L6-v2"),
        )

    raise ConfigurationError(
        f"Unknown embedding provider: {provider_name!r}. "
        "Valid options: jina, ollama, openai, sentence_transformers"
    )
