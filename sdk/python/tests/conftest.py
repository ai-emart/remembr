from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

from remembr import RemembrClient


class MockAPI:
    def __init__(self) -> None:
        self.responses: list[httpx.Response] = []
        self.requests: list[httpx.Request] = []

    def enqueue(self, response: httpx.Response) -> None:
        self.responses.append(response)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            return httpx.Response(
                500,
                request=request,
                json={"error": {"message": "No mocked response queued", "code": "TEST_ERROR"}},
            )

        response = self.responses.pop(0)
        response.request = request
        return response


@pytest.fixture
def mock_client() -> tuple[RemembrClient, MockAPI]:
    api = MockAPI()
    transport = httpx.MockTransport(api.handler)

    client = RemembrClient(api_key="test-key", base_url="https://example.test")
    client._client = httpx.AsyncClient(
        base_url=client.base_url,
        headers={
            "X-API-Key": client.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        transport=transport,
        timeout=httpx.Timeout(client.timeout),
    )

    return client, api


@pytest.fixture
async def live_client() -> RemembrClient:
    api_key = os.getenv("REMEMBR_TEST_API_KEY")
    if not api_key:
        pytest.skip("REMEMBR_TEST_API_KEY is not set; skipping live integration tests")

    base_url = os.getenv("REMEMBR_TEST_BASE_URL", "http://localhost:8000/api/v1")
    async with RemembrClient(api_key=api_key, base_url=base_url, timeout=30) as client:
        yield client


@pytest.fixture
def sample_session() -> dict[str, Any]:
    return {
        "request_id": "req_123",
        "session_id": "sess_123",
        "org_id": "org_123",
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {"topic": "tests"},
    }


@pytest.fixture
def sample_episode() -> dict[str, Any]:
    return {
        "episode_id": "ep_123",
        "session_id": "sess_123",
        "role": "user",
        "content": "hello world",
        "created_at": "2026-01-01T00:00:00Z",
        "tags": ["alpha"],
        "metadata": {"source": "unit-test"},
    }
