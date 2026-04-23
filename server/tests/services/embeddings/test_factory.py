"""Tests for the embedding provider factory."""

from __future__ import annotations

import pytest

from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.factory import (
    ConfigurationError,
    _create_provider,
    get_embedding_provider,
    set_embedding_provider_override,
)


class _StubProvider(EmbeddingProvider):
    @property
    def model(self) -> str:
        return "stub"

    @property
    def dimensions(self) -> int | None:
        return 4

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        return [0.0] * 4, 4

    async def generate_embeddings_batch(self, texts):
        return [([0.0] * 4, 4)] * len(texts)


@pytest.fixture(autouse=True)
def reset_provider():
    yield
    set_embedding_provider_override(None)


def test_override_takes_precedence():
    stub = _StubProvider()
    set_embedding_provider_override(stub)
    assert get_embedding_provider() is stub


def test_override_none_clears():
    stub = _StubProvider()
    set_embedding_provider_override(stub)
    set_embedding_provider_override(None)
    # After clearing override, factory will try to create a real provider.
    # We just assert the override path is gone (no assertion on returned type needed).
    assert get_embedding_provider() is not stub


def test_jina_provider_requires_api_key(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "jina")
    monkeypatch.delenv("JINA_API_KEY", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises((ConfigurationError, Exception)):
            _create_provider()
    finally:
        get_settings.cache_clear()


def test_openai_provider_requires_api_key(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises((ConfigurationError, Exception)):
            _create_provider()
    finally:
        get_settings.cache_clear()


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "unknown_xyz")

    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises((ConfigurationError, Exception)):
            _create_provider()
    finally:
        get_settings.cache_clear()
