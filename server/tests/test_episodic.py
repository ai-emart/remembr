"""Unit tests for EpisodicMemory service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.services.embeddings import EmbeddingProvider, set_embedding_provider_override
from app.services.episodic import EpisodicMemory
from app.services.scoping import MemoryScope
from app.services.search_config import SearchWeights


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
async def test_log_dispatches_celery_task(
    scope: MemoryScope,
    monkeypatch: pytest.MonkeyPatch,
):
    """log() should persist the episode and dispatch a Celery task."""
    fake_db = object()
    svc = EpisodicMemory(db=fake_db)

    fake_episode = type("E", (), {"id": uuid.uuid4(), "embedding_status": "pending"})()
    mocked_log = AsyncMock(return_value=fake_episode)
    monkeypatch.setattr("app.services.episodic.episode_repo.log_episode", mocked_log)

    dispatched = []

    def _capture_delay(episode_id):
        dispatched.append(episode_id)

    from app.tasks import embeddings as emb_tasks

    monkeypatch.setattr(emb_tasks.generate_embedding_for_episode, "delay", _capture_delay)

    episode = await svc.log(scope=scope, role="user", content="hello")

    assert episode is fake_episode
    mocked_log.assert_awaited_once()
    assert dispatched == [str(fake_episode.id)]


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
    assert "WITH filtered_episodes" in str(fake_db.last_sql)
    assert "ts_rank_cd" in str(fake_db.last_sql)
    assert "EXP(" in str(fake_db.last_sql)


@pytest.mark.asyncio
async def test_search_keyword_uses_tsquery_and_rank(scope: MemoryScope):
    row = type("Row", (), dict(
        id=uuid.uuid4(),
        org_id=uuid.UUID(scope.org_id),
        team_id=None,
        user_id=None,
        agent_id=None,
        session_id=None,
        role="assistant",
        content="SKU ZX-9000 is backordered until Friday.",
        tags=["inventory"],
        metadata={"source": "erp"},
        created_at=datetime(2026, 1, 5, tzinfo=UTC),
        similarity_score=0.52,
    ))()

    fake_db = _FakeDB(rows=[row])
    svc = EpisodicMemory(db=fake_db)

    results = await svc.search_keyword(
        scope=scope,
        query="ZX-9000",
        tags=["inventory"],
        limit=4,
    )

    assert len(results) == 1
    assert results[0].similarity_score == pytest.approx(0.52)
    assert fake_db.last_params["query"] == "ZX-9000"
    assert "plainto_tsquery('english', :query)" in str(fake_db.last_sql)
    assert "ts_rank_cd" in str(fake_db.last_sql)
    assert "search_vector @@" in str(fake_db.last_sql)


@pytest.mark.asyncio
async def test_search_hybrid_passes_weight_params(scope: MemoryScope):
    row = type("Row", (), dict(
        id=uuid.uuid4(),
        org_id=uuid.UUID(scope.org_id),
        team_id=None,
        user_id=None,
        agent_id=None,
        session_id=None,
        role="assistant",
        content="Recent but slightly less exact match.",
        tags=["support"],
        metadata={},
        created_at=datetime(2026, 1, 6, tzinfo=UTC),
        similarity_score=0.67,
    ))()

    fake_db = _FakeDB(rows=[row])
    fake_provider = _FakeProvider(vector=[0.2, 0.6, 0.8])
    set_embedding_provider_override(fake_provider)

    svc = EpisodicMemory(db=fake_db)
    weights = SearchWeights(semantic=0.2, keyword=0.2, recency=0.6)
    await svc.search_hybrid(scope=scope, query="recent support issue", limit=2, weights=weights)

    assert fake_db.last_params["semantic_weight"] == pytest.approx(0.2)
    assert fake_db.last_params["keyword_weight"] == pytest.approx(0.2)
    assert fake_db.last_params["recency_weight"] == pytest.approx(0.6)


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
