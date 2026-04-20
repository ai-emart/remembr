from fastapi import APIRouter, Depends, Request
from loguru import logger
from redis.exceptions import RedisError

from app.api.responses import StandardResponse, success
from app.api.v1 import api_keys, auth, export, memory
from app.config import get_settings
from app.middleware.context import RequestContext, require_auth
from app.middleware.rate_limit import limiter

router = APIRouter()

# Include routers
router.include_router(auth.router)
router.include_router(api_keys.router)
router.include_router(memory.router)
router.include_router(export.router)


@router.get("/health", response_model=StandardResponse[dict])
@limiter.exempt
async def health_check(request: Request):
    """
    Health check endpoint.

    Returns:
        Health status with environment, version, and Redis status
    """
    settings = get_settings()

    # Check Redis connection
    redis_status = "unknown"
    try:
        from app.db.redis import get_redis_client

        redis = get_redis_client()
        await redis.ping()
        redis_status = "healthy"

    except RuntimeError:
        # Redis not initialized
        redis_status = "not_initialized"
        logger.warning("Redis not initialized during health check")

    except RedisError as e:
        # Redis connection error
        redis_status = "unhealthy"
        logger.error("Redis health check failed", error=str(e))

    except Exception as e:
        # Unexpected error
        redis_status = "error"
        logger.error("Unexpected error in Redis health check", error=str(e))

    logger.debug("Health check requested", redis_status=redis_status)

    return success(
        {
            "status": "ok",
            "environment": settings.environment,
            "version": "0.1.0",
            "redis_status": redis_status,
        },
        request_id=request.state.request_id,
    )


@router.get("/me", response_model=StandardResponse[dict])
async def get_current_context_info(
    request: Request,
    ctx: RequestContext = Depends(require_auth),
):
    """
    Get current authentication context.

    Demonstrates the context middleware by returning the authenticated
    user's context information.

    Requires authentication via JWT or API key.

    Returns:
        Context information including org_id, user_id, agent_id, auth_method
    """
    logger.info(
        "Context info requested",
        org_id=str(ctx.org_id),
        auth_method=ctx.auth_method,
    )

    return success(
        {
            "org_id": str(ctx.org_id),
            "user_id": str(ctx.user_id) if ctx.user_id else None,
            "agent_id": str(ctx.agent_id) if ctx.agent_id else None,
            "auth_method": ctx.auth_method,
        },
        request_id=request.state.request_id,
    )
