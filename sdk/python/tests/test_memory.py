from __future__ import annotations

import httpx
import pytest

from remembr import RemembrClient


@pytest.mark.asyncio
async def test_store_returns_episode(mock_client, sample_episode) -> None:
    client, api = mock_client
    api.enqueue(httpx.Response(201, json={"data": sample_episode}))

    episode = await client.store(
        content="hello world",
        role="user",
        session_id="sess_123",
        tags=["alpha"],
        metadata={"source": "unit-test"},
    )

    assert episode.episode_id == "ep_123"
    assert episode.session_id == "sess_123"
    assert episode.tags == ["alpha"]


@pytest.mark.asyncio
async def test_search_returns_results_sorted_by_score(mock_client, sample_episode) -> None:
    client, api = mock_client
    results = [
        {**sample_episode, "episode_id": "ep_high", "score": 0.99},
        {**sample_episode, "episode_id": "ep_mid", "score": 0.75},
        {**sample_episode, "episode_id": "ep_low", "score": 0.21},
    ]
    api.enqueue(
        httpx.Response(
            200,
            json={"data": {"request_id": "req_search", "results": results, "total": 3, "query_time_ms": 12}},
        )
    )

    response = await client.search(query="hello")
    scores = [result.score for result in response.results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_search_with_filters(mock_client, sample_episode) -> None:
    client, api = mock_client
    filtered = [{**sample_episode, "episode_id": "ep_filtered", "score": 0.88, "tags": ["billing"]}]
    api.enqueue(
        httpx.Response(
            200,
            json={"data": {"request_id": "req_filter", "results": filtered, "total": 1, "query_time_ms": 8}},
        )
    )

    response = await client.search(
        query="bill",
        tags=["billing"],
        search_mode="keyword",
        weights={"semantic": 0.6, "keyword": 0.3, "recency": 0.1},
    )
    assert len(response.results) == 1
    assert response.results[0].tags == ["billing"]


@pytest.mark.asyncio
async def test_get_session_history_chronological(mock_client, sample_episode) -> None:
    client, api = mock_client
    older = {**sample_episode, "episode_id": "ep_old", "created_at": "2026-01-01T00:00:00Z"}
    newer = {**sample_episode, "episode_id": "ep_new", "created_at": "2026-01-01T00:01:00Z"}
    api.enqueue(httpx.Response(200, json={"data": {"episodes": [older, newer], "total": 2}}))

    episodes = await client.get_session_history("sess_123", limit=50)
    created = [episode.created_at for episode in episodes]
    assert created == sorted(created)
