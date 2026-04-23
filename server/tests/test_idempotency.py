"""Tests for the idempotency middleware."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app.middleware.idempotency import (
    IDEMPOTENCY_TTL_SECONDS,
    MAX_KEY_LENGTH,
    _cache_key,
    _tenant_token,
    idempotency_middleware,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_scope():
    """Return a minimal ASGI scope dict."""
    return {
        "type": "http",
        "method": "POST",
        "path": "/memory",
        "query_string": b"",
        "headers": [],
    }


def _make_request(
    method: str = "POST",
    idempotency_key: str | None = None,
    auth: str = "Bearer test-token",
) -> Request:
    headers = [(b"authorization", auth.encode())]
    if idempotency_key is not None:
        headers.append((b"idempotency-key", idempotency_key.encode()))
    scope = {
        "type": "http",
        "method": method,
        "path": "/memory",
        "query_string": b"",
        "headers": headers,
    }
    return Request(scope)


async def _plain_200(request: Request) -> StreamingResponse:
    body = json.dumps({"data": {"episode_id": "abc"}}).encode()

    async def _gen():
        yield body

    return StreamingResponse(
        _gen(),
        status_code=200,
        media_type="application/json",
    )


async def _plain_400(request: Request) -> StreamingResponse:
    body = json.dumps({"error": {"message": "bad request"}}).encode()

    async def _gen():
        yield body

    return StreamingResponse(
        _gen(),
        status_code=400,
        media_type="application/json",
    )


# ── cache key helpers ─────────────────────────────────────────────────────────


def test_tenant_token_is_deterministic():
    request = _make_request(auth="Bearer abc123")
    assert _tenant_token(request) == _tenant_token(request)


def test_tenant_token_differs_by_auth():
    r1 = _make_request(auth="Bearer org1-token")
    r2 = _make_request(auth="Bearer org2-token")
    assert _tenant_token(r1) != _tenant_token(r2)


def test_cache_key_format():
    key = _cache_key("tenant123", "my-op-id")
    assert key == "idempotency:tenant123:my-op-id"


# ── skip non-idempotency-keyed requests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_no_idempotency_key_passes_through():
    """Requests without Idempotency-Key go straight to the route."""
    request = _make_request(idempotency_key=None)
    response = await idempotency_middleware(request, _plain_200)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_request_passes_through():
    """GET requests are never cached even if the header is present."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/memory",
        "query_string": b"",
        "headers": [(b"idempotency-key", b"some-key"), (b"authorization", b"Bearer tok")],
    }
    request = Request(scope)
    response = await idempotency_middleware(request, _plain_200)
    assert response.status_code == 200


# ── validation ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_key_returns_400():
    request = _make_request(idempotency_key="   ")
    response = await idempotency_middleware(request, _plain_200)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_key_too_long_returns_400():
    request = _make_request(idempotency_key="x" * (MAX_KEY_LENGTH + 1))
    response = await idempotency_middleware(request, _plain_200)
    assert response.status_code == 400


# ── cache miss → cache set ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_miss_calls_route_and_stores():
    """On cache miss, the route is executed and the response body is stored in Redis."""
    request = _make_request(idempotency_key="op-001")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # cache miss
    mock_redis.setex = AsyncMock()

    with patch("app.db.redis.get_redis_client", return_value=mock_redis):
        response = await idempotency_middleware(request, _plain_200)

    assert response.status_code == 200
    mock_redis.setex.assert_awaited_once()
    call_args = mock_redis.setex.await_args
    assert call_args.args[1] == IDEMPOTENCY_TTL_SECONDS
    stored = json.loads(call_args.args[2])
    assert stored["status"] == 200
    assert base64.b64decode(stored["body"]) == b'{"data": {"episode_id": "abc"}}'


# ── cache hit → replay ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_hit_replays_without_calling_route():
    """On cache hit, the route is NOT called and the cached response is returned."""
    request = _make_request(idempotency_key="op-002")
    cached_body = json.dumps({"data": {"episode_id": "cached"}}).encode()
    cached_entry = json.dumps(
        {
            "status": 200,
            "headers": {"content-type": "application/json"},
            "body": base64.b64encode(cached_body).decode(),
        }
    ).encode()

    mock_redis = AsyncMock()
    mock_redis.get.return_value = cached_entry

    route_called = []

    async def _route(req: Request) -> StreamingResponse:
        route_called.append(True)

        async def _gen():
            yield b"should not be called"

        return StreamingResponse(_gen(), status_code=200)

    with patch("app.db.redis.get_redis_client", return_value=mock_redis):
        response = await idempotency_middleware(request, _route)

    assert route_called == [], "Route must NOT be called on cache hit"
    assert response.status_code == 200
    assert response.headers.get("x-idempotent-replay") == "true"
    assert b"cached" in response.body


# ── errors not cached ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_4xx_response_not_cached():
    """4xx responses are not stored in Redis."""
    request = _make_request(idempotency_key="op-003")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.setex = AsyncMock()

    with patch("app.db.redis.get_redis_client", return_value=mock_redis):
        response = await idempotency_middleware(request, _plain_400)

    assert response.status_code == 400
    mock_redis.setex.assert_not_awaited()


# ── per-org (per-auth) isolation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_same_key_different_auth_uses_different_cache_slots():
    """Two callers with different auth tokens get different cache keys."""
    key = "shared-op-id"
    r1 = _make_request(idempotency_key=key, auth="Bearer org1-token")
    r2 = _make_request(idempotency_key=key, auth="Bearer org2-token")
    ck1 = _cache_key(_tenant_token(r1), key)
    ck2 = _cache_key(_tenant_token(r2), key)
    assert ck1 != ck2


# ── Redis unavailable → fail open ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_unavailable_fails_open():
    """When Redis is unavailable, the route still processes normally."""
    request = _make_request(idempotency_key="op-004")

    with patch("app.db.redis.get_redis_client", side_effect=RuntimeError("no redis")):
        response = await idempotency_middleware(request, _plain_200)

    assert response.status_code == 200


# ── TTL assertion ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stored_with_24h_ttl():
    """Response is stored with exactly IDEMPOTENCY_TTL_SECONDS (86400) TTL."""
    request = _make_request(idempotency_key="op-005")
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.setex = AsyncMock()

    with patch("app.db.redis.get_redis_client", return_value=mock_redis):
        await idempotency_middleware(request, _plain_200)

    ttl_arg = mock_redis.setex.await_args.args[1]
    assert ttl_arg == 86_400
