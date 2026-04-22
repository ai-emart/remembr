from __future__ import annotations

import httpx
import pytest


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
            json={
                "data": {
                    "request_id": "req_search",
                    "results": results,
                    "total": 3,
                    "query_time_ms": 12,
                }
            },
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
            json={
                "data": {
                    "request_id": "req_filter",
                    "results": filtered,
                    "total": 1,
                    "query_time_ms": 8,
                }
            },
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


@pytest.mark.asyncio
async def test_webhook_lifecycle_methods(mock_client) -> None:
    client, api = mock_client
    api.enqueue(
        httpx.Response(
            201,
            json={
                "data": {
                    "id": "wh_1",
                    "org_id": "org_1",
                    "url": "https://example.com/hooks",
                    "events": ["memory.stored"],
                    "active": True,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "last_delivery_at": None,
                    "last_delivery_status": None,
                    "failure_count": 0,
                    "secret": "secret_once",
                }
            },
        )
    )
    api.enqueue(
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "wh_1",
                        "org_id": "org_1",
                        "url": "https://example.com/hooks",
                        "events": ["memory.stored"],
                        "active": True,
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                        "last_delivery_at": None,
                        "last_delivery_status": None,
                        "failure_count": 0,
                    }
                ]
            },
        )
    )
    api.enqueue(
        httpx.Response(
            200,
            json={
                "data": {
                    "id": "wh_1",
                    "org_id": "org_1",
                    "url": "https://example.com/hooks-updated",
                    "events": ["checkpoint.created"],
                    "active": False,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                    "last_delivery_at": None,
                    "last_delivery_status": None,
                    "failure_count": 0,
                }
            },
        )
    )
    api.enqueue(
        httpx.Response(
            200,
            json={
                "data": {
                    "id": "wh_1",
                    "org_id": "org_1",
                    "url": "https://example.com/hooks-updated",
                    "events": ["checkpoint.created"],
                    "active": False,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                    "last_delivery_at": None,
                    "last_delivery_status": None,
                    "failure_count": 0,
                    "secret": "secret_rotated",
                }
            },
        )
    )
    api.enqueue(
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "del_1",
                        "webhook_id": "wh_1",
                        "event": "memory.stored",
                        "payload": {"episode_id": "ep_1"},
                        "status": "delivered",
                        "attempts": 1,
                        "last_attempt_at": "2026-01-02T00:00:00Z",
                        "response_status_code": 204,
                        "response_body_snippet": "ok",
                        "created_at": "2026-01-02T00:00:00Z",
                    }
                ]
            },
        )
    )
    api.enqueue(
        httpx.Response(
            200,
            json={"data": {"delivery_id": "del_test", "event": "webhook.test"}},
        )
    )
    api.enqueue(
        httpx.Response(
            200,
            json={"data": {"deleted": True, "webhook_id": "wh_1"}},
        )
    )

    created = await client.webhooks.create(
        url="https://example.com/hooks",
        events=["memory.stored"],
    )
    listed = await client.webhooks.list()
    updated = await client.webhooks.update(
        "wh_1",
        url="https://example.com/hooks-updated",
        events=["checkpoint.created"],
        active=False,
    )
    rotated = await client.webhooks.rotate_secret("wh_1")
    deliveries = await client.webhooks.deliveries("wh_1")
    tested = await client.webhooks.test("wh_1")
    deleted = await client.webhooks.delete("wh_1")

    assert created.secret == "secret_once"
    assert listed[0].id == "wh_1"
    assert updated.url == "https://example.com/hooks-updated"
    assert rotated.secret == "secret_rotated"
    assert deliveries[0].event == "memory.stored"
    assert tested["delivery_id"] == "del_test"
    assert deleted["deleted"] is True
