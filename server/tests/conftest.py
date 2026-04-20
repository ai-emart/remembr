"""Pytest configuration and fixtures for tests."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(autouse=True)
def _mock_embedding_task(monkeypatch):
    """Prevent Celery tasks from dispatching to Redis during tests.

    Tests that want to exercise the task body directly should call
    _do_generate_embedding() or _mark_failed() from app.tasks.embeddings
    using asyncio.run() in a sync test or awaiting them directly.
    """
    from app.tasks.embeddings import generate_embedding_for_episode

    monkeypatch.setattr(generate_embedding_for_episode, "delay", lambda *a, **kw: None)


@pytest_asyncio.fixture(scope="function")
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with isolated schema lifecycle."""
    from app.config import get_test_settings
    from app.db.base import Base

    settings = get_test_settings()

    # Create a new engine for each test to avoid event loop issues
    test_engine = create_async_engine(
        settings.database_url.get_secret_value().replace("postgresql://", "postgresql+asyncpg://"),
        echo=False,
        pool_pre_ping=True,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )

    test_session_local = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_local() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with database and Redis dependencies overridden."""
    from app.db.redis import close_redis, init_redis
    from app.db.session import get_db
    from app.main import app

    await init_redis()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    await close_redis()
