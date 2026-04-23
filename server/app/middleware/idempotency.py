"""Idempotency middleware for safe replay of POST/PUT/PATCH requests.

When a request includes an `Idempotency-Key` header, the response is cached in
Redis for 24 hours keyed by `idempotency:{tenant_token}:{idempotency_key}`.
Replaying the same key returns the cached response without re-executing the route.

Tenant isolation is achieved by hashing the raw Authorization header so that
two different callers cannot collide even if they send the same key string.

Only 2xx responses are cached — errors are never replayed.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable

from loguru import logger
from starlette.requests import Request
from starlette.responses import Response

IDEMPOTENCY_TTL_SECONDS = 86_400  # 24 hours
IDEMPOTENCY_METHODS = {"POST", "PUT", "PATCH"}
MAX_KEY_LENGTH = 255
_CACHE_NS = "idempotency"


def _tenant_token(request: Request) -> str:
    """Hash the Authorization header to produce a per-tenant discriminator."""
    auth = request.headers.get("authorization", "")
    return hashlib.sha256(auth.encode()).hexdigest()[:32]


def _cache_key(tenant: str, idempotency_key: str) -> str:
    return f"{_CACHE_NS}:{tenant}:{idempotency_key}"


async def idempotency_middleware(request: Request, call_next: Callable) -> Response:
    """FastAPI http middleware for idempotent request handling."""
    key_header = request.headers.get("idempotency-key")

    if not key_header or request.method not in IDEMPOTENCY_METHODS:
        return await call_next(request)

    # Validate key
    if not key_header.strip():
        return Response(
            content=json.dumps({"error": {"message": "Idempotency-Key must be non-empty"}}),
            status_code=400,
            media_type="application/json",
        )
    if len(key_header) > MAX_KEY_LENGTH:
        return Response(
            content=json.dumps(
                {"error": {"message": f"Idempotency-Key must be ≤ {MAX_KEY_LENGTH} characters"}}
            ),
            status_code=400,
            media_type="application/json",
        )

    tenant = _tenant_token(request)
    cache_key = _cache_key(tenant, key_header)

    redis = None
    try:
        from app.db.redis import get_redis_client

        redis = get_redis_client()
    except RuntimeError:
        # Redis unavailable — fail open
        logger.warning("Idempotency: Redis unavailable, processing request without cache")
        return await call_next(request)

    # ── Cache hit ──────────────────────────────────────────────────────────
    try:
        cached_raw = await redis.get(cache_key)
    except Exception as exc:
        logger.warning("Idempotency: Redis GET failed, failing open", error=str(exc))
        return await call_next(request)

    if cached_raw:
        try:
            cached = json.loads(cached_raw)
            body = base64.b64decode(cached["body"])
            headers = {k: v for k, v in cached["headers"].items()}
            headers["X-Idempotent-Replay"] = "true"
            logger.debug("Idempotency cache hit", cache_key=cache_key)
            return Response(
                content=body,
                status_code=cached["status"],
                headers=headers,
                media_type=headers.get("content-type", "application/json"),
            )
        except Exception as exc:
            logger.warning("Idempotency: Failed to deserialize cache entry", error=str(exc))

    # ── Cache miss — run the route ─────────────────────────────────────────
    response = await call_next(request)

    if response.status_code < 200 or response.status_code >= 300:
        return response

    # Consume the response body so we can cache and re-serve it
    body_chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        body_chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    body = b"".join(body_chunks)

    cacheable_headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in {"transfer-encoding", "content-length"}
    }

    try:
        payload = json.dumps(
            {
                "status": response.status_code,
                "headers": cacheable_headers,
                "body": base64.b64encode(body).decode(),
            }
        )
        await redis.setex(cache_key, IDEMPOTENCY_TTL_SECONDS, payload)
        logger.debug("Idempotency cache stored", cache_key=cache_key, ttl=IDEMPOTENCY_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Idempotency: Failed to store cache entry", error=str(exc))

    return Response(
        content=body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.headers.get("content-type", "application/json"),
    )
