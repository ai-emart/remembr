"""Unit tests for memory API endpoint handlers."""

from __future__ import annotations

import os
import sys
import types
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from starlette.requests import Request
from starlette.responses import Response

if "tiktoken" not in sys.modules:
    fake_tiktoken = types.ModuleType("tiktoken")

    class _FakeEncoding:
        def encode(self, text: str):
            return [1] * max(len(text.split()), 1)

    fake_tiktoken.get_encoding = lambda _name: _FakeEncoding()
    sys.modules["tiktoken"] = fake_tiktoken

os.environ.setdefault("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/remembr_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-memory-api-tests")
os.environ.setdefault("JINA_API_KEY", "test-jina-key")

from app.api.v1.memory import (
    CheckpointListItem,
    CreateSessionRequest,
    LogMemoryRequest,
    MemoryQueryRequest,
    RestoreSessionRequest,
    create_session,
    create_session_checkpoint,
    delete_memory_episode,
    delete_session_memories,
    delete_user_memories,
    get_session,
    get_session_history,
    list_session_checkpoints,
    list_sessions,
    log_memory,
    memory_diff,
    restore_session_checkpoint,
    search_memory,
)
from app.exceptions import AuthorizationError, NotFoundError
from app.middleware.context import RequestContext
from app.services.short_term import SessionMessage


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value

    def scalars(self):
        class _Scalars:
            def __init__(self, value):
                self._value = value

            def all(self):
                return self._value

        return _Scalars(self._value)

    def all(self):
        return self._value


@pytest.fixture
def ctx() -> RequestContext:
    return RequestContext(
        request_id="req-123",
        org_id=uuid4(),
        user_id=uuid4(),
        agent_id=None,
        auth_method="jwt",
    )


@pytest.mark.asyncio
async def test_create_session_and_log_memory(monkeypatch, ctx):
    db = AsyncMock()
    redis = AsyncMock()

    session_id = uuid4()
    episode = SimpleNamespace(
        id=uuid4(),
        session_id=session_id,
        created_at=datetime.now(UTC),
        org_id=ctx.org_id,
        role="user",
        content="hello",
        tags=[],
        embedding_status="pending",
    )

    async def _refresh_session(session_obj):
        session_obj.id = session_id
        session_obj.created_at = datetime.now(UTC)

    db.refresh.side_effect = _refresh_session
    db.execute.return_value = _ScalarResult(SimpleNamespace(id=session_id, org_id=ctx.org_id))

    mock_episodic = Mock()
    mock_episodic.log = AsyncMock(return_value=episode)
    monkeypatch.setattr("app.api.v1.memory.EpisodicMemory", lambda db: mock_episodic)

    mock_short_term = Mock()
    mock_short_term.token_count.return_value = 7
    mock_short_term.add_message = AsyncMock()
    monkeypatch.setattr("app.api.v1.memory.ShortTermMemory", lambda cache, db: mock_short_term)

    created = await create_session(CreateSessionRequest(metadata={"m": 1}), ctx, db)
    logged = await log_memory(
        LogMemoryRequest(role="user", content="hello", session_id=session_id),
        ctx,
        db,
        redis,
    )

    assert created.request_id == "req-123"
    assert created.data.session_id == str(session_id)
    assert logged.data.token_count == 7
    assert logged.data.session_id == str(session_id)


@pytest.mark.asyncio
async def test_checkpoint_and_restore(monkeypatch, ctx):
    db = AsyncMock()
    redis = AsyncMock()

    session_id = uuid4()
    checkpoint_id = uuid4()
    checkpoint_episode = SimpleNamespace(
        id=checkpoint_id,
        created_at=datetime.now(UTC),
        metadata_={"message_count": 2},
    )

    db.execute.side_effect = [
        _ScalarResult(
            SimpleNamespace(
                id=session_id, org_id=ctx.org_id, team_id=None, user_id=ctx.user_id, agent_id=None
            )
        ),
        _ScalarResult(checkpoint_episode),
        _ScalarResult(
            SimpleNamespace(
                id=session_id, org_id=ctx.org_id, team_id=None, user_id=ctx.user_id, agent_id=None
            )
        ),
        _ScalarResult(checkpoint_episode),
    ]

    mock_short_term = Mock()
    mock_short_term.checkpoint = AsyncMock(return_value=str(checkpoint_id))
    mock_short_term.restore_from_checkpoint = AsyncMock(return_value=2)
    monkeypatch.setattr("app.api.v1.memory.ShortTermMemory", lambda cache, db: mock_short_term)

    checkpoint = await create_session_checkpoint(session_id, ctx, db, redis)
    restored = await restore_session_checkpoint(
        session_id,
        RestoreSessionRequest(checkpoint_id=checkpoint_id),
        ctx,
        db,
        redis,
    )

    assert checkpoint.data.checkpoint_id == str(checkpoint_id)
    assert checkpoint.data.message_count == 2
    assert restored.data.restored_message_count == 2


@pytest.mark.asyncio
async def test_cross_org_and_missing_checkpoint_return_404(monkeypatch, ctx):
    db = AsyncMock()
    redis = AsyncMock()

    db.execute.return_value = _ScalarResult(None)
    with pytest.raises(NotFoundError) as missing_session:
        await log_memory(
            LogMemoryRequest(role="user", content="x", session_id=uuid4()),
            ctx,
            db,
            redis,
        )
    assert missing_session.value.status_code == 404

    db.execute.side_effect = [
        _ScalarResult(
            SimpleNamespace(
                id=uuid4(), org_id=ctx.org_id, team_id=None, user_id=ctx.user_id, agent_id=None
            )
        ),
        _ScalarResult(None),
    ]
    monkeypatch.setattr("app.api.v1.memory.ShortTermMemory", lambda cache, db: Mock())
    with pytest.raises(NotFoundError) as missing_checkpoint:
        await restore_session_checkpoint(
            uuid4(),
            RestoreSessionRequest(checkpoint_id=uuid4()),
            ctx,
            db,
            redis,
        )
    assert missing_checkpoint.value.status_code == 404


@pytest.mark.asyncio
async def test_search_memory_enforces_limit_and_returns_results(monkeypatch, ctx):
    db = AsyncMock()

    session_id = uuid4()
    db.execute.return_value = _ScalarResult(
        SimpleNamespace(
            id=session_id, org_id=ctx.org_id, team_id=None, user_id=ctx.user_id, agent_id=None
        )
    )

    fake_engine = Mock()
    fake_engine.query = AsyncMock(
        return_value=(
            [
                {
                    "episode_id": str(uuid4()),
                    "content": "found",
                    "role": "user",
                    "score": 0.92,
                    "created_at": datetime.now(UTC),
                    "tags": ["a"],
                }
            ],
            1,
            12,
        )
    )
    monkeypatch.setattr("app.api.v1.memory.MemoryQueryEngine", lambda episodic: fake_engine)

    response = await search_memory.__wrapped__(
        Request({"type": "http", "method": "POST", "path": "/api/v1/memory/search", "headers": []}),
        Response(),
        MemoryQueryRequest(query="needle", session_id=session_id, limit=100),
        ctx,
        db,
    )
    assert response.data.total == 1
    assert response.data.query_time_ms == 12
    assert response.data.results[0].content == "found"


@pytest.mark.asyncio
async def test_list_sessions_get_session_history_and_checkpoints(monkeypatch, ctx):
    db = AsyncMock()
    redis = AsyncMock()

    session_id = uuid4()
    session = SimpleNamespace(
        id=session_id,
        org_id=ctx.org_id,
        team_id=None,
        user_id=ctx.user_id,
        agent_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        metadata_={"topic": "demo"},
    )
    episode = SimpleNamespace(
        id=uuid4(),
        session_id=session_id,
        role="user",
        content="hello",
        tags=["x"],
        metadata_={"k": "v"},
        created_at=datetime.now(UTC),
    )

    db.execute.side_effect = [
        _ScalarResult(1),
        _ScalarResult([session]),
        _ScalarResult([(session_id, 3)]),
        _ScalarResult(session),
        _ScalarResult(session),
        _ScalarResult(1),
        _ScalarResult([episode]),
        _ScalarResult(session),
    ]

    mock_short_term = Mock()
    mock_short_term.MAX_TOKENS = 4000
    mock_short_term.get_context = AsyncMock(
        return_value=[
            SessionMessage(
                role="user",
                content="hello",
                tokens=2,
                priority_score=1.0,
                timestamp=datetime.now(UTC),
            )
        ]
    )
    mock_short_term.list_checkpoints = AsyncMock(
        return_value=[
            {
                "checkpoint_id": str(uuid4()),
                "created_at": datetime.now(UTC),
                "message_count": 2,
            }
        ]
    )
    monkeypatch.setattr("app.api.v1.memory.ShortTermMemory", lambda cache, db: mock_short_term)

    sessions_response = await list_sessions(ctx, db, limit=20, offset=0)
    assert sessions_response.data.total == 1
    assert sessions_response.data.sessions[0].message_count == 3

    session_response = await get_session(session_id, ctx, db, redis)
    assert session_response.data.token_usage["used"] == 2

    history_response = await get_session_history(session_id, ctx, db, limit=20, offset=0)
    assert history_response.data.total == 1
    assert history_response.data.episodes[0].content == "hello"

    checkpoints_response = await list_session_checkpoints(session_id, ctx, db, redis)
    assert isinstance(checkpoints_response.data.checkpoints[0], CheckpointListItem)


@pytest.mark.asyncio
async def test_forgetting_endpoints(monkeypatch, ctx):
    db = AsyncMock()
    redis = AsyncMock()

    session_id = uuid4()
    db.execute.return_value = _ScalarResult(
        SimpleNamespace(
            id=session_id,
            org_id=ctx.org_id,
            team_id=None,
            user_id=ctx.user_id,
            agent_id=None,
        )
    )

    fake_service = Mock()
    fake_service.delete_episode = AsyncMock(
        return_value=SimpleNamespace(deleted=True, restorable_until=None)
    )
    fake_service.delete_session_memories = AsyncMock(return_value=(3, None))
    fake_service.delete_user_memories = AsyncMock(
        return_value=SimpleNamespace(deleted_episodes=10, deleted_sessions=2)
    )
    monkeypatch.setattr("app.api.v1.memory.ForgettingService", lambda db, redis: fake_service)

    episode_resp = await delete_memory_episode(uuid4(), ctx, db, redis)
    assert episode_resp.data.deleted is True

    session_resp = await delete_session_memories(session_id, ctx, db, redis)
    assert session_resp.data.deleted_count == 3

    with pytest.raises(AuthorizationError) as forbidden:
        await delete_user_memories(uuid4(), ctx, db, redis)
    assert forbidden.value.status_code == 403


@pytest.mark.asyncio
async def test_memory_diff(monkeypatch, ctx):
    db = AsyncMock()
    now = datetime.now(UTC)
    later = now

    episode = SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        role="user",
        content="delta",
        tags=["tag1"],
        created_at=now,
        org_id=ctx.org_id,
        team_id=None,
        user_id=ctx.user_id,
        agent_id=None,
    )
    db.execute.return_value = _ScalarResult([episode])

    response = await memory_diff(
        from_time=now,
        to_time=later,
        session_id=None,
        user_id=None,
        role=None,
        tags=None,
        ctx=ctx,
        db=db,
    )
    assert response.data.count == 1
    assert response.data.added[0].content == "delta"
