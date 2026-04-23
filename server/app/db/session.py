"""Database session management."""

import os
from collections.abc import AsyncGenerator

from loguru import logger
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

settings = get_settings()

_db_url = settings.database_url.get_secret_value().replace("postgresql://", "postgresql+asyncpg://")

# PgBouncer transaction-mode pooling requires:
#   1. NullPool — SQLAlchemy must not hold open connections; pgbouncer owns the pool.
#   2. statement_cache_size=0 — prepared statements cannot survive transaction boundaries.
_use_pgbouncer = "pgbouncer" in _db_url.lower() or os.getenv("USE_PGBOUNCER", "").lower() in {
    "1",
    "true",
    "yes",
}

_connect_args: dict = {
    "statement_cache_size": 0,
    "prepared_statement_cache_size": 0,
}

if _use_pgbouncer:
    from sqlalchemy.pool import NullPool

    logger.info("PgBouncer detected — using NullPool + disabled prepared statement cache")
    engine = create_async_engine(
        _db_url,
        echo=settings.log_level == "DEBUG",
        poolclass=NullPool,
        connect_args=_connect_args,
    )
else:
    engine = create_async_engine(
        _db_url,
        echo=settings.log_level == "DEBUG",
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        connect_args=_connect_args,
    )

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database sessions.

    Automatically sets the organization context from the request context
    if available, enabling Row-Level Security.
    """
    from app.db.rls import set_org_context
    from app.middleware.context import get_current_context

    async with AsyncSessionLocal() as session:
        try:
            ctx = get_current_context()
            if ctx and ctx.org_id:
                await set_org_context(session, ctx.org_id)
                logger.debug(
                    "Database session initialized with org context",
                    org_id=str(ctx.org_id),
                )

            yield session
            await session.commit()
        except SATimeoutError as exc:
            logger.warning(
                "Database connection pool timeout (possible pool exhaustion)",
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout,
                error=str(exc),
            )
            await session.rollback()
            raise
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
