"""Cache service for Redis operations."""

import json
from typing import Any

from loguru import logger
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.observability import record_cache_access

# TTL constants (in seconds)
SESSION_TTL = 3600  # 1 hour
SHORT_TERM_TTL = 1800  # 30 minutes
LONG_TERM_TTL = 86400  # 24 hours


def make_key(namespace: str, *parts: str) -> str:
    """
    Create a namespaced Redis key.

    Args:
        namespace: Key namespace (e.g., 'session', 'user', 'agent')
        *parts: Additional key parts

    Returns:
        Formatted key string

    Example:
        >>> make_key('session', 'user123', 'data')
        'remembr:session:user123:data'
    """
    all_parts = ["remembr", namespace] + list(parts)
    return ":".join(str(part) for part in all_parts)


class CacheService:
    """Service for Redis caching operations."""

    def __init__(self, redis: Redis):
        """
        Initialize cache service.

        Args:
            redis: Redis client instance
        """
        self.redis = redis

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Set a value in cache with optional TTL.

        Args:
            key: Cache key (should use make_key())
            value: Value to cache (will be JSON serialized)
            ttl_seconds: Time to live in seconds (None = no expiration)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Serialize value to JSON
            serialized = json.dumps(value)

            # Set with TTL if provided
            if ttl_seconds:
                await self.redis.setex(key, ttl_seconds, serialized)
            else:
                await self.redis.set(key, serialized)

            logger.debug("Cache set", key=key, ttl=ttl_seconds)
            return True

        except (RedisError, TypeError, ValueError) as e:
            logger.error("Cache set failed", key=key, error=str(e))
            return False

    async def get(self, key: str) -> dict | list | str | int | float | bool | None:
        """
        Get a value from cache.

        Args:
            key: Cache key

        Returns:
            Deserialized value or None if not found
        """
        try:
            value = await self.redis.get(key)

            if value is None:
                record_cache_access(False)
                logger.debug("Cache miss", key=key)
                return None

            # Deserialize from JSON
            deserialized = json.loads(value)
            record_cache_access(True)
            logger.debug("Cache hit", key=key)
            return deserialized

        except (RedisError, json.JSONDecodeError) as e:
            logger.error("Cache get failed", key=key, error=str(e))
            return None

    async def delete(self, key: str) -> bool:
        """
        Delete a key from cache.

        Args:
            key: Cache key

        Returns:
            True if key was deleted, False if key didn't exist
        """
        try:
            result = await self.redis.delete(key)
            deleted = result > 0

            logger.debug("Cache delete", key=key, deleted=deleted)
            return deleted

        except RedisError as e:
            logger.error("Cache delete failed", key=key, error=str(e))
            return False

    async def exists(self, key: str) -> bool:
        """
        Check if a key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if key exists, False otherwise
        """
        try:
            result = await self.redis.exists(key)
            return result > 0

        except RedisError as e:
            logger.error("Cache exists check failed", key=key, error=str(e))
            return False

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        """
        Set expiration time for a key.

        Args:
            key: Cache key
            ttl_seconds: Time to live in seconds

        Returns:
            True if expiration was set, False otherwise
        """
        try:
            result = await self.redis.expire(key, ttl_seconds)
            logger.debug("Cache expire set", key=key, ttl=ttl_seconds)
            return result

        except RedisError as e:
            logger.error("Cache expire failed", key=key, error=str(e))
            return False

    async def ttl(self, key: str) -> int:
        """
        Get remaining time to live for a key.

        Args:
            key: Cache key

        Returns:
            TTL in seconds, -1 if no expiration, -2 if key doesn't exist
        """
        try:
            return await self.redis.ttl(key)
        except RedisError as e:
            logger.error("Cache TTL check failed", key=key, error=str(e))
            return -2

    async def increment(self, key: str, amount: int = 1) -> int | None:
        """
        Increment a numeric value in cache.

        Args:
            key: Cache key
            amount: Amount to increment by

        Returns:
            New value after increment, or None on error
        """
        try:
            result = await self.redis.incrby(key, amount)
            logger.debug("Cache increment", key=key, amount=amount, new_value=result)
            return result

        except RedisError as e:
            logger.error("Cache increment failed", key=key, error=str(e))
            return None

    async def set_many(
        self,
        mapping: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Set multiple key-value pairs.

        Args:
            mapping: Dictionary of key-value pairs
            ttl_seconds: Optional TTL for all keys

        Returns:
            True if successful, False otherwise
        """
        try:
            # Serialize all values
            serialized = {k: json.dumps(v) for k, v in mapping.items()}

            # Use pipeline for efficiency
            async with self.redis.pipeline() as pipe:
                await pipe.mset(serialized)

                # Set TTL for each key if provided
                if ttl_seconds:
                    for key in serialized.keys():
                        await pipe.expire(key, ttl_seconds)

                await pipe.execute()

            logger.debug("Cache set many", count=len(mapping), ttl=ttl_seconds)
            return True

        except (RedisError, TypeError, ValueError) as e:
            logger.error("Cache set many failed", error=str(e))
            return False

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """
        Get multiple values from cache.

        Args:
            keys: List of cache keys

        Returns:
            Dictionary of key-value pairs (only existing keys)
        """
        try:
            values = await self.redis.mget(keys)

            result = {}
            for key, value in zip(keys, values):
                if value is not None:
                    try:
                        result[key] = json.loads(value)
                    except json.JSONDecodeError:
                        logger.warning("Failed to deserialize cached value", key=key)

            logger.debug("Cache get many", requested=len(keys), found=len(result))
            return result

        except RedisError as e:
            logger.error("Cache get many failed", error=str(e))
            return {}

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        Args:
            pattern: Redis key pattern (e.g., 'remembr:session:*')

        Returns:
            Number of keys deleted
        """
        try:
            keys = []
            async for key in self.redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                deleted = await self.redis.delete(*keys)
                logger.debug("Cache delete pattern", pattern=pattern, deleted=deleted)
                return deleted

            return 0

        except RedisError as e:
            logger.error("Cache delete pattern failed", pattern=pattern, error=str(e))
            return 0
