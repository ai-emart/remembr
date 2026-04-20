"""Rate limiting configuration for FastAPI using SlowAPI + Redis storage."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request
from loguru import logger

from app.config import get_settings

try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware

    _SLOWAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    _SLOWAPI_AVAILABLE = False

    class RateLimitExceeded(Exception):
        pass

    class Limiter:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, _value: Callable[[], str] | str):
            def decorator(fn):
                return fn

            return decorator

        def exempt(self, fn):
            return fn


def _token_from_request(request: Request) -> str:
    """Resolve limiter key using API key/JWT token string, fallback to client ip."""
    auth_header = request.headers.get("authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        return token or (request.client.host if request.client else "unknown")

    x_api_key = request.headers.get("x-api-key", "").strip()
    if x_api_key:
        return x_api_key

    return request.client.host if request.client else "unknown"


def get_default_limit() -> str:
    settings = get_settings()
    return f"{settings.rate_limit_default_per_minute}/minute"


def get_search_limit() -> str:
    settings = get_settings()
    return f"{settings.rate_limit_search_per_minute}/minute"


def create_limiter() -> Limiter:
    settings = get_settings()
    redis_url = settings.redis_url.get_secret_value()

    if not _SLOWAPI_AVAILABLE:
        logger.warning("slowapi is not installed; rate limiting is disabled")
        return Limiter()

    logger.info(
        "Initializing API rate limiter",
        default_limit=get_default_limit(),
        search_limit=get_search_limit(),
    )
    return Limiter(
        key_func=_token_from_request,
        storage_uri=redis_url,
        default_limits=[get_default_limit()],
        headers_enabled=True,
        storage_options={
            "socket_connect_timeout": 1,
            "socket_timeout": 1,
        },
    )


limiter = create_limiter()


def setup_rate_limiting(app) -> None:
    """Attach slowapi middleware + exception handler to app."""
    app.state.limiter = limiter

    if not _SLOWAPI_AVAILABLE:
        return

    async def custom_rate_limit_handler(request: Request, exc: Exception):
        detail = getattr(exc, "detail", str(exc))
        request_id = getattr(request.state, "request_id", "unknown")

        from fastapi.responses import JSONResponse

        return JSONResponse(
            {
                "error": {
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit exceeded: {detail}",
                    "details": None,
                    "request_id": request_id,
                }
            },
            status_code=429,
        )

    def _handle_storage_error(request: Request, exc: Exception) -> None:
        """Fail open when Redis is unavailable — let auth decide the response."""
        logger.warning(f"Rate limiter storage unavailable ({type(exc).__name__}), failing open")
        return None

    app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)

    # Register handlers for Redis-specific exceptions (exact type match used by slowapi)
    try:
        from redis.exceptions import (
            ConnectionError as RedisConnectionError,
            TimeoutError as RedisTimeoutError,
        )

        app.add_exception_handler(RedisTimeoutError, _handle_storage_error)
        app.add_exception_handler(RedisConnectionError, _handle_storage_error)
    except ImportError:
        pass

    # Patch sync_check_limits to fail open for any unhandled storage error
    import slowapi.middleware as _slowapi_middleware

    _orig_sync_check_limits = _slowapi_middleware.sync_check_limits

    def _safe_sync_check_limits(limiter, request, handler, app_):
        try:
            return _orig_sync_check_limits(limiter, request, handler, app_)
        except Exception:
            logger.warning("Rate limiter storage error in sync_check_limits, failing open")
            return None, False

    _slowapi_middleware.sync_check_limits = _safe_sync_check_limits

    app.add_middleware(SlowAPIMiddleware)
