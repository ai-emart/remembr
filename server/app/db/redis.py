"""Redis client configuration and management."""

from collections.abc import AsyncGenerator

from loguru import logger
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError

from app.config import get_settings

# Global Redis client instance
_redis_client: Redis | None = None
_connection_pool: ConnectionPool | None = None


async def init_redis() -> None:
    """
    Initialize Redis connection pool and client.

    Called during application startup.
    """
    global _redis_client, _connection_pool

    settings = get_settings()
    redis_url = settings.redis_url.get_secret_value()

    try:
        # Create connection pool
        _connection_pool = ConnectionPool.from_url(
            redis_url,
            max_connections=20,
            decode_responses=True,
            encoding="utf-8",
        )

        # Create Redis client
        _redis_client = Redis(connection_pool=_connection_pool)

        # Test connection
        await _redis_client.ping()

        logger.info("Redis connection established", url=redis_url.split("@")[-1])

    except RedisError as e:
        logger.error("Failed to connect to Redis", error=str(e))
        raise


async def close_redis() -> None:
    """
    Close Redis connection pool.

    Called during application shutdown.
    """
    global _redis_client, _connection_pool

    if _redis_client:
        await _redis_client.aclose()
        logger.info("Redis connection closed")

    if _connection_pool:
        await _connection_pool.disconnect()
        _connection_pool = None

    _redis_client = None


async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    Dependency for getting Redis client in FastAPI routes.

    Yields:
        Redis client instance

    Raises:
        RuntimeError: If Redis is not initialized
    """
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")

    yield _redis_client


def get_redis_client() -> Redis:
    """
    Get Redis client instance directly (for use outside FastAPI routes).

    Returns:
        Redis client instance

    Raises:
        RuntimeError: If Redis is not initialized
    """
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")

    return _redis_client
