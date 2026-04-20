"""Tests for Ollama embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.embeddings.ollama import OllamaEmbeddingProvider


@pytest.fixture
def provider():
    return OllamaEmbeddingProvider(base_url="http://localhost:11434", model="nomic-embed-text")


def test_model_property(provider):
    assert provider.model == "nomic-embed-text"


def test_dimensions_is_none(provider):
    assert provider.dimensions is None


@pytest.mark.asyncio
async def test_generate_embedding_success(provider):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"embedding": [0.5, 0.6, 0.7]}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        vector, dims = await provider.generate_embedding("test text")

    assert vector == [0.5, 0.6, 0.7]
    assert dims == 3


@pytest.mark.asyncio
async def test_generate_embedding_error_raises(provider):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal error"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValueError, match="Ollama error 500"):
            await provider.generate_embedding("test")


@pytest.mark.asyncio
async def test_generate_embeddings_batch(provider):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"embedding": [1.0, 2.0]}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        results = await provider.generate_embeddings_batch(["a", "b"])

    assert len(results) == 2
    assert all(r == ([1.0, 2.0], 2) for r in results)
