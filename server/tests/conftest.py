"""Pytest configuration and fixtures for tests."""

from collections.abc import AsyncGenerator
from fnmatch import fnmatch
from time import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytest_plugins = ("pytest_asyncio",)


class _FakePipeline:
    def __init__(self, redis: "_FakeRedis") -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple, dict]] = []

    async def __aenter__(self) -> "_FakePipeline":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def __getattr__(self, name: str):
        async def _op(*args, **kwargs):
            self._ops.append((name, args, kwargs))
            return self

        return _op

    async def execute(self):
        results = []
        for name, args, kwargs in self._ops:
            method = getattr(self._redis, name)
            results.append(await method(*args, **kwargs))
        self._ops.clear()
        return results


class _FakeRedis(Redis):
    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._expiry: dict[str, float] = {}

    def _purge_expired(self) -> None:
        now = time()
        expired = [key for key, deadline in self._expiry.items() if deadline <= now]
        for key in expired:
            self._store.pop(key, None)
            self._expiry.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(self)

    async def get(self, key: str):
        self._purge_expired()
        return self._store.get(key)

    async def set(self, key: str, value: str) -> bool:
        self._store[key] = value
        self._expiry.pop(key, None)
        return True

    async def setex(self, key: str, ttl_seconds: int, value: str) -> bool:
        self._store[key] = value
        self._expiry[key] = time() + ttl_seconds
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._store:
                removed += 1
                self._store.pop(key, None)
                self._expiry.pop(key, None)
        return removed

    async def exists(self, key: str) -> int:
        self._purge_expired()
        return int(key in self._store)

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        self._purge_expired()
        if key not in self._store:
            return False
        self._expiry[key] = time() + ttl_seconds
        return True

    async def ttl(self, key: str) -> int:
        self._purge_expired()
        if key not in self._store:
            return -2
        deadline = self._expiry.get(key)
        if deadline is None:
            return -1
        return max(int(deadline - time()), 0)

    async def incrby(self, key: str, amount: int = 1) -> int:
        self._purge_expired()
        current = int(self._store.get(key, "0"))
        new_value = current + amount
        self._store[key] = str(new_value)
        return new_value

    async def mset(self, mapping: dict[str, str]) -> bool:
        self._store.update(mapping)
        for key in mapping:
            self._expiry.pop(key, None)
        return True

    async def mget(self, keys: list[str]):
        self._purge_expired()
        return [self._store.get(key) for key in keys]

    async def llen(self, key: str) -> int:
        self._purge_expired()
        value = self._store.get(key)
        if value is None:
            return 0
        if isinstance(value, list):
            return len(value)
        return 0

    async def scan_iter(self, match: str | None = None):
        self._purge_expired()
        for key in list(self._store):
            if match is None or fnmatch(key, match):
                yield key


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
    from sqlalchemy import text

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
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        except DBAPIError as err:
            message = str(err).lower()
            await test_engine.dispose()
            if 'extension "vector" is not available' in message:
                pytest.skip("pgvector extension is not available in the configured test database")
            raise

    async with test_session_local() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await test_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with database and Redis dependencies overridden."""
    from app.db import redis as redis_module
    from app.db.session import get_db
    from app.main import app

    fake_redis = _FakeRedis()
    redis_module._redis_client = fake_redis
    redis_module._connection_pool = SimpleNamespace(disconnect=lambda: None)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    redis_module._redis_client = None
    redis_module._connection_pool = None
