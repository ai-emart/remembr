"""Tests for short-term memory service."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.scoping import MemoryScope
from app.services.short_term import SessionMessage, ShortTermMemory

class _FakePipeline:
    def __init__(self, redis_store: dict[str, str]) -> None:
        self._redis_store = redis_store
        self._ops: list[tuple] = []

    async def __aenter__(self) -> "_FakePipeline":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def delete(self, key: str) -> None:
        self._ops.append(("delete", key))

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._ops.append(("setex", key, ttl, value))

    async def execute(self) -> None:
        for op in self._ops:
            if op[0] == "delete":
                self._redis_store.pop(op[1], None)
            elif op[0] == "setex":
                self._redis_store[op[1]] = op[3]


class _FakeRedis:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        return _FakePipeline(redis_store=self._store)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class _FakeDB:
    def __init__(self, scoped_session, episodes=None) -> None:
        self.scoped_session = scoped_session
        self.episodes = episodes or []

    def add(self, episode) -> None:
        if getattr(episode, "id", None) is None:
            episode.id = uuid.uuid4()
        if getattr(episode, "created_at", None) is None:
            episode.created_at = datetime.now(UTC)
        self.episodes.append(episode)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj) -> None:
        return None

    async def execute(self, query):
        query_text = str(query)

        if "FROM sessions" in query_text:
            return _FakeResult(self.scoped_session)

        if "WHERE episodes.id =" in query_text:
            checkpoint_id = query.compile().params.get("id_1")
            for episode in self.episodes:
                if str(episode.id) == str(checkpoint_id):
                    return _FakeResult(episode)
            return _FakeResult(None)

        return _FakeResult(self.episodes)


@pytest.mark.asyncio
async def test_priority_scoring_is_deterministic() -> None:
    """Same input message should always produce same score."""
    cache = AsyncMock()
    memory = ShortTermMemory(cache=cache, max_tokens=4000)

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    message = SessionMessage(
        role="user",
        content="hello world",
        tokens=memory.token_count("hello world"),
        priority_score=0,
        timestamp=ts,
    )

    score_1 = memory._score_priority(message)
    score_2 = memory._score_priority(message)

    assert score_1 == score_2


@pytest.mark.asyncio
async def test_compression_removes_low_priority_messages() -> None:
    """Compression should drop lowest priority entries when token budget is exceeded."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=[])
    cache.set = AsyncMock(return_value=True)

    memory = ShortTermMemory(cache=cache, max_tokens=12)

    base_ts = datetime(2024, 1, 1, tzinfo=UTC)
    
    # Create messages with explicit priority scores
    # System messages have highest priority (role_weight=3.0)
    system_msg = SessionMessage(
        role="system",
        content="instruction",
        tokens=4,
        priority_score=memory._score_priority(SessionMessage(
            role="system",
            content="instruction",
            tokens=4,
            priority_score=0,
            timestamp=base_ts,
        )),
        timestamp=base_ts,
    )
    
    # Assistant messages have lowest priority (role_weight=1.0)
    assistant_msg = SessionMessage(
        role="assistant",
        content="verbose response example",
        tokens=6,
        priority_score=memory._score_priority(SessionMessage(
            role="assistant",
            content="verbose response example",
            tokens=6,
            priority_score=0,
            timestamp=base_ts + timedelta(seconds=1),
        )),
        timestamp=base_ts + timedelta(seconds=1),
    )
    
    # User messages have medium priority (role_weight=2.0)
    user_msg = SessionMessage(
        role="user",
        content="question",
        tokens=4,
        priority_score=memory._score_priority(SessionMessage(
            role="user",
            content="question",
            tokens=4,
            priority_score=0,
            timestamp=base_ts + timedelta(seconds=2),
        )),
        timestamp=base_ts + timedelta(seconds=2),
    )

    await memory.add_message("session-1", system_msg)
    cache.get = AsyncMock(return_value=cache.set.call_args.args[1])
    await memory.add_message("session-1", assistant_msg)
    cache.get = AsyncMock(return_value=cache.set.call_args.args[1])
    await memory.add_message("session-1", user_msg)
    cache.get = AsyncMock(return_value=cache.set.call_args.args[1])

    context = await memory.get_context("session-1")

    roles = [msg.role for msg in context]
    total_tokens = sum(msg.tokens for msg in context)
    
    # Should compress to fit within 12 tokens
    assert total_tokens <= 12, f"Total tokens {total_tokens} exceeds limit of 12"
    
    # Assistant should be removed (lowest priority)
    # System and user should remain
    assert "assistant" not in roles, f"Assistant should be removed, but roles are: {roles}"
    assert "system" in roles, f"System should be kept, but roles are: {roles}"
    assert "user" in roles, f"User should be kept, but roles are: {roles}"


@pytest.mark.asyncio
async def test_checkpoint_modify_restore_cycle() -> None:
    """Checkpoint then modify context and restore should rewind to checkpoint state."""
    session_id = str(uuid.uuid4())
    scope = MemoryScope(org_id=str(uuid.uuid4()), level="org")
    scoped_session = SimpleNamespace(
        id=uuid.UUID(session_id),
        org_id=uuid.UUID(scope.org_id),
        team_id=None,
        user_id=None,
        agent_id=None,
    )

    redis_store: dict[str, str] = {}
    cache = AsyncMock()
    cache.redis = _FakeRedis(redis_store)
    cache.set = AsyncMock(
        side_effect=lambda key, value, ttl_seconds=None: redis_store.__setitem__(
            key,
            json.dumps(value),
        )
    )
    cache.get = AsyncMock(
        side_effect=lambda key: json.loads(redis_store[key]) if key in redis_store else None
    )

    db = _FakeDB(scoped_session=scoped_session)
    memory = ShortTermMemory(cache=cache, db=db, max_tokens=100)

    base_ts = datetime(2024, 1, 1, tzinfo=UTC)
    message_1 = SessionMessage("system", "rules", 10, 1, base_ts)
    message_2 = SessionMessage("user", "question", 12, 1, base_ts + timedelta(seconds=1))

    await memory.add_message(session_id, message_1)
    await memory.add_message(session_id, message_2)

    checkpoint_id = await memory.checkpoint(session_id=session_id, scope=scope)

    await memory.add_message(
        session_id,
        SessionMessage("assistant", "temporary", 6, 1, base_ts + timedelta(seconds=2)),
    )
    assert len(await memory.get_context(session_id)) == 3

    restored_count = await memory.restore_from_checkpoint(
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        scope=scope,
    )

    restored_context = await memory.get_context(session_id)
    assert restored_count == 2
    assert len(restored_context) == 2
    assert [msg.content for msg in restored_context] == ["rules", "question"]
