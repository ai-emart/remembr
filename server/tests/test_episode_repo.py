"""Unit tests for episodic repository helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.repositories import episode_repo
from app.services.scoping import MemoryScope

pytestmark = pytest.mark.integration


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class _FakeSession:
    def __init__(self, execute_result=None):
        self.execute_result = execute_result
        self.added = []
        self.deleted = []
        self.flushed = False
        self.refreshed = False
        self.last_query = None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed = True

    async def refresh(self, _value):
        self.refreshed = True

    async def execute(self, query):
        self.last_query = query
        return self.execute_result

    async def delete(self, value):
        self.deleted.append(value)


@pytest.fixture
def scope() -> MemoryScope:
    return MemoryScope(
        org_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        level="user",
    )


@pytest.mark.asyncio
async def test_log_episode_persists_defaults(scope: MemoryScope):
    db = _FakeSession()

    episode = await episode_repo.log_episode(
        db=db,
        scope=scope,
        role="user",
        content="hello",
    )

    assert db.flushed is True
    assert db.refreshed is True
    assert db.added
    assert episode.role == "user"
    assert episode.tags == []
    assert episode.metadata_ == {}


@pytest.mark.asyncio
async def test_list_episodes_applies_tags_and_time_filters(scope: MemoryScope):
    db = _FakeSession(execute_result=_FakeScalarResult([]))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)

    await episode_repo.list_episodes(
        db=db,
        scope=scope,
        tags=["alpha", "beta"],
        role="assistant",
        from_time=start,
        to_time=end,
        limit=10,
        offset=5,
    )

    query_sql = str(
        db.last_query.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "episodes.tags" in query_sql
    assert "&&" in query_sql
    assert "episodes.role = 'assistant'" in query_sql
    assert "episodes.created_at >=" in query_sql
    assert "episodes.created_at <=" in query_sql
    assert "LIMIT 10" in query_sql
    assert "OFFSET 5" in query_sql


@pytest.mark.asyncio
async def test_count_episodes_returns_scalar(scope: MemoryScope):
    db = _FakeSession(execute_result=_FakeScalarResult(7))

    count = await episode_repo.count_episodes(db=db, scope=scope)

    assert count == 7


@pytest.mark.asyncio
async def test_delete_episode_noops_if_missing(scope: MemoryScope, monkeypatch: pytest.MonkeyPatch):
    db = _FakeSession()

    async def _missing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(episode_repo, "get_episode", _missing)

    await episode_repo.delete_episode(db=db, episode_id=str(uuid.uuid4()), scope=scope)

    assert db.deleted == []


@pytest.mark.asyncio
async def test_delete_episode_deletes_found(scope: MemoryScope, monkeypatch: pytest.MonkeyPatch):
    db = _FakeSession()
    target = SimpleNamespace(id=uuid.uuid4(), deleted_at=None)

    async def _found(*_args, **_kwargs):
        return target

    monkeypatch.setattr(episode_repo, "get_episode", _found)

    await episode_repo.delete_episode(db=db, episode_id=str(target.id), scope=scope)

    # Soft-delete: deleted_at is set, db.delete() is NOT called
    assert target.deleted_at is not None
    assert db.deleted == []
    assert db.flushed is True
