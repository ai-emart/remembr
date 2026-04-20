"""Unit tests for EpisodicMemory service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.services.embeddings import EmbeddingProvider, set_embedding_provider_override
from app.services.episodic import EpisodicMemory
from app.services.scoping import MemoryScope


class _FakeProvider(EmbeddingProvider):
    """Minimal fake provider for tests."""

    def __init__(self, vector: list[float] | None = None) -> None:
        self._vector = vector or [0.1, 0.2]
        self._generate = AsyncMock(return_value=(self._vector, len(self._vector)))

    @property
    def model(self) -> str:
        return "fake-model"

    @property
    def dimensions(self) -> int | None:
        return len(self._vector)

    async def generate_embedding(self, text: str) -> tuple[list[float], int]:
        return await self._generate(text)

    async def generate_embeddings_batch(
        self, texts: list[str]
    ) -> list[tuple[list[float], int]]:
        return [await self.generate_embedding(t) for t in texts]


@pytest.fixture(autouse=True)
def reset_provider():
    """Reset the global provider override after each test."""
    yield
    set_embedding_provider_override(None)


class _BackgroundDB:
    def __init__(self, episode):
        self.episode = episode
        self.added = []
        self.committed = False

    async def get(self, _model, _id):
        return self.episode

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.committed = True


class _SessionFactory:
    def __init__(self, db):
        self.db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.last_sql = None
        self.last_params = None

    async def execute(self, sql, params):
        self.last_sql = sql
        self.last_params = params
        return _FakeExecuteResult(self.rows)


@pytest.fixture
def scope() -> MemoryScope:
    return MemoryScope(org_id=str(uuid.uuid4()), level="org")


@pytest.mark.asyncio
async def test_log_is_non_blocking_and_schedules_embedding(
    scope: MemoryScope,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_db = object()
    svc = EpisodicMemory(db=fake_db)

    fake_episode = object.__new__(type("E", (), {"id": uuid.uuid4()}))
    fake_episode = type("E", (), {"id": uuid.uuid4()})()
    mocked_log = AsyncMock(return_value=fake_episode)
    monkeypatch.setattr("app.services.episodic.episode_repo.log_episode", mocked_log)

    scheduled = {}

    def _capture_create_task(coro):
        scheduled["coro"] = coro
        coro.close()
        return object()

    monkeypatch.setattr("app.services.episodic.asyncio.create_task", _capture_create_task)

    episode = await svc.log(scope=scope, role="user", content="hello")

    assert episode is fake_episode
    mocked_log.assert_awaited_once()
    assert "coro" in scheduled


@pytest.mark.asyncio
async def test_replay_session_orders_ascending(scope: MemoryScope, monkeypatch: pytest.MonkeyPatch):
    svc = EpisodicMemory(db=object())

    e1 = type("E", (), {"created_at": datetime(2026, 1, 2, tzinfo=UTC), "id": uuid.uuid4()})()
    e2 = type("E", (), {"created_at": datetime(2026, 1, 1, tzinfo=UTC), "id": uuid.uuid4()})()

    mocked_list = AsyncMock(return_value=[e1, e2])
    monkeypatch.setattr("app.services.episodic.episode_repo.list_episodes", mocked_list)

    replay = await svc.replay_session(scope=scope, session_id=str(uuid.uuid4()))

    assert [item.id for item in replay] == [e2.id, e1.id]


@pytest.mark.asyncio
async def test_background_embedding_persists_record(scope: MemoryScope):
    episode = type("E", (), {"id": uuid.uuid4(), "org_id": uuid.uuid4()})()
    background_db = _BackgroundDB(episode=episode)

    fake_provider = _FakeProvider(vector=[0.1, 0.2])
    set_embedding_provider_override(fake_provider)

    svc = EpisodicMemory(
        db=object(),
        session_factory=_SessionFactory(background_db),
    )

    await svc._generate_and_store_embedding(episode.id, "content")

    assert background_db.committed is True
    assert len(background_db.added) == 1
    added = background_db.added[0]
    assert added.episode_id == episode.id
    assert added.dimensions == 2


@pytest.mark.asyncio
async def test_search_by_tags_delegates_to_repo(
    scope: MemoryScope,
    monkeypatch: pytest.MonkeyPatch,
):
    svc = EpisodicMemory(db=object())

    mocked_list = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.episodic.episode_repo.list_episodes", mocked_list)

    await svc.search_by_tags(scope=scope, tags=["a"], limit=3)

    mocked_list.assert_awaited_once()
    kwargs = mocked_list.await_args.kwargs
    assert kwargs["tags"] == ["a"]
    assert kwargs["limit"] == 3


@pytest.mark.asyncio
async def test_search_semantic_returns_similarity_results(scope: MemoryScope):
    row = type("Row", (), dict(
        id=uuid.uuid4(),
        org_id=uuid.UUID(scope.org_id),
        team_id=None,
        user_id=None,
        agent_id=None,
        session_id=None,
        role="assistant",
        content="Try marinating the tofu in tamari and ginger.",
        tags=["cooking"],
        metadata={"source": "chat"},
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        similarity_score=0.93,
    ))()

    fake_db = _FakeDB(rows=[row])
    fake_provider = _FakeProvider(vector=[0.2, 0.4, 0.8])
    set_embedding_provider_override(fake_provider)

    svc = EpisodicMemory(db=fake_db)
    results = await svc.search_semantic(
        scope=scope,
        query="best way to season tofu",
        limit=5,
        score_threshold=0.7,
    )

    assert len(results) == 1
    assert results[0].episode.content.startswith("Try marinating")
    assert results[0].similarity_score == pytest.approx(0.93)
    assert fake_db.last_params["score_threshold"] == 0.7
    assert "<=>" in str(fake_db.last_sql)


@pytest.mark.asyncio
async def test_search_hybrid_combines_semantic_with_filters(scope: MemoryScope):
    row = type("Row", (), dict(
        id=uuid.uuid4(),
        org_id=uuid.UUID(scope.org_id),
        team_id=None,
        user_id=None,
        agent_id=None,
        session_id=None,
        role="assistant",
        content="Password reset requires identity verification first.",
        tags=["support", "security"],
        metadata={"ticket": "abc"},
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
        similarity_score=0.88,
    ))()

    fake_db = _FakeDB(rows=[row])
    fake_provider = _FakeProvider(vector=[0.1, 0.3, 0.9])
    set_embedding_provider_override(fake_provider)

    svc = EpisodicMemory(db=fake_db)
    from_time = datetime(2026, 1, 1, tzinfo=UTC)
    to_time = datetime(2026, 1, 4, tzinfo=UTC)

    results = await svc.search_hybrid(
        scope=scope,
        query="helped customer recover account",
        tags=["support"],
        from_time=from_time,
        to_time=to_time,
        role="assistant",
        limit=3,
        score_threshold=0.65,
    )

    assert len(results) == 1
    assert results[0].episode.tags == ["support", "security"]
    assert results[0].similarity_score == pytest.approx(0.88)
    assert fake_db.last_params["tags"] == ["support"]
    assert fake_db.last_params["role"] == "assistant"
    assert "WITH semantic_candidates" in str(fake_db.last_sql)


@pytest.mark.asyncio
async def test_reconstruct_state_at_returns_snapshot(
    scope: MemoryScope, monkeypatch: pytest.MonkeyPatch
):
    older = type("E", (), {"created_at": datetime(2026, 1, 1, 9, tzinfo=UTC), "id": uuid.uuid4()})()
    newer = type("E", (), {"created_at": datetime(2026, 1, 1, 15, tzinfo=UTC), "id": uuid.uuid4()})()

    mocked_list = AsyncMock(return_value=[newer, older])
    monkeypatch.setattr("app.services.episodic.episode_repo.list_episodes", mocked_list)

    svc = EpisodicMemory(db=object())
    snapshot = await svc.reconstruct_state_at(
        scope=scope,
        timestamp=datetime(2026, 1, 1, 16, tzinfo=UTC),
    )

    assert [item.id for item in snapshot] == [older.id, newer.id]
    kwargs = mocked_list.await_args.kwargs
    assert kwargs["to_time"] == datetime(2026, 1, 1, 16, tzinfo=UTC)
