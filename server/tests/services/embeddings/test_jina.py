"""Tests for Jina AI embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.embeddings.jina import JinaEmbeddingProvider


@pytest.fixture
def provider():
    return JinaEmbeddingProvider(api_key="test-key", model="jina-embeddings-v3")


def test_model_property(provider):
    assert provider.model == "jina-embeddings-v3"


def test_dimensions_is_none(provider):
    assert provider.dimensions is None


@pytest.mark.asyncio
async def test_generate_embedding_returns_vector(provider):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        vector, dims = await provider.generate_embedding("hello world")

    assert vector == [0.1, 0.2, 0.3]
    assert dims == 3


@pytest.mark.asyncio
async def test_generate_embeddings_batch_empty(provider):
    result = await provider.generate_embeddings_batch([])
    assert result == []


@pytest.mark.asyncio
async def test_generate_embeddings_batch_success(provider):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"embedding": [0.1, 0.2]},
            {"embedding": [0.3, 0.4]},
        ]
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        results = await provider.generate_embeddings_batch(["a", "b"])

    assert len(results) == 2
    assert results[0] == ([0.1, 0.2], 2)
    assert results[1] == ([0.3, 0.4], 2)
