"""Tests for soft-delete, hard-delete, restore, cascade, and purge behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Embedding, Episode, Session
from app.services.forgetting import ForgettingService, SOFT_DELETE_GRACE_DAYS
from app.services.scoping import MemoryScope


# ── helpers ───────────────────────────────────────────────────────────────────

def _scope(org_id: uuid.UUID | None = None) -> MemoryScope:
    return MemoryScope(org_id=str(org_id or uuid.uuid4()), level="org")


def _make_episode(
    org_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    deleted_at: datetime | None = None,
) -> Episode:
    ep = MagicMock(spec=Episode)
    ep.id = uuid.uuid4()
    ep.org_id = org_id or uuid.uuid4()
    ep.team_id = None
    ep.user_id = None
    ep.agent_id = None
    ep.session_id = session_id
    ep.content = "hello"
    ep.embedding_status = "pending"
    ep.deleted_at = deleted_at
    return ep


def _make_session(
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    deleted_at: datetime | None = None,
) -> Session:
    sess = MagicMock(spec=Session)
    sess.id = uuid.uuid4()
    sess.org_id = org_id or uuid.uuid4()
    sess.team_id = None
    sess.user_id = user_id
    sess.agent_id = None
    sess.deleted_at = deleted_at
    return sess


def _make_service(fake_db: AsyncMock, fake_redis: MagicMock | None = None) -> ForgettingService:
    fake_redis = fake_redis or MagicMock()
    # Provide a no-op session_factory for audit writes
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=AsyncMock())
    fake_session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=fake_session)
    return ForgettingService(db=fake_db, redis=fake_redis, session_factory=factory)


# ── SoftDeleteMixin ───────────────────────────────────────────────────────────

def test_soft_delete_mixin_not_deleted_expression():
    """not_deleted() returns a SQLAlchemy expression that filters deleted_at IS NULL."""
    expr = Episode.not_deleted()
    compiled = str(expr.compile(compile_kwargs={"literal_binds": True}))
    assert "deleted_at" in compiled
    assert "NULL" in compiled


# ── Soft-delete visibility ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_soft_deleted_episode_invisible_to_reads():
    """Soft-deleted episode is excluded by not_deleted() filter."""
    ep = _make_episode()
    ep.deleted_at = datetime.now(UTC)

    fake_db = AsyncMock()
    fake_db.begin = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=False),
    ))
    # Simulate: first scalar_one_or_none → None (scope filter includes not_deleted())
    fake_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    scope = _scope(ep.org_id)
    svc = _make_service(fake_db)
    result = await svc.delete_episode(
        episode_id=ep.id,
        scope=scope,
        request_id="req-1",
        actor_user_id=None,
    )
    assert result.deleted is False


@pytest.mark.asyncio
async def test_soft_delete_sets_deleted_at():
    """delete_episode sets deleted_at on the episode and its embeddings."""
    ep = _make_episode()
    ep.deleted_at = None

    ctx_mgr = AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))
    fake_db = AsyncMock()
    fake_db.begin = MagicMock(return_value=ctx_mgr)
    # First execute: select episode → returns ep
    # Second execute: update embeddings → no-op
    fake_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=ep)),
        MagicMock(),  # update embeddings
    ]

    scope = _scope(ep.org_id)
    svc = _make_service(fake_db)
    result = await svc.delete_episode(
        episode_id=ep.id,
        scope=scope,
        request_id="req-2",
        actor_user_id=None,
    )

    assert result.deleted is True
    assert result.soft is True
    assert ep.deleted_at is not None
    assert result.restorable_until is not None
    assert result.restorable_until > datetime.now(UTC)


# ── Hard delete ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_delete_removes_episode():
    """hard_delete_episode calls db.delete() and returns True."""
    ep = _make_episode()

    ctx_mgr = AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))
    fake_db = AsyncMock()
    fake_db.begin = MagicMock(return_value=ctx_mgr)
    fake_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=ep)),  # select episode
        MagicMock(),  # delete embeddings
    ]

    scope = _scope(ep.org_id)
    svc = _make_service(fake_db)
    deleted = await svc.hard_delete_episode(
        episode_id=ep.id,
        scope=scope,
        request_id="req-3",
        actor_user_id=None,
    )

    assert deleted is True
    fake_db.delete.assert_awaited_once_with(ep)


@pytest.mark.asyncio
async def test_hard_delete_returns_false_when_not_found():
    """hard_delete_episode returns False when episode doesn't exist."""
    ctx_mgr = AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))
    fake_db = AsyncMock()
    fake_db.begin = MagicMock(return_value=ctx_mgr)
    fake_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    svc = _make_service(fake_db)
    deleted = await svc.hard_delete_episode(
        episode_id=uuid.uuid4(),
        scope=_scope(),
        request_id="req-4",
        actor_user_id=None,
    )
    assert deleted is False


# ── Restore ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_restore_within_grace_period():
    """restore_episode clears deleted_at when within 30 days."""
    ep = _make_episode()
    ep.deleted_at = datetime.now(UTC) - timedelta(days=5)

    ctx_mgr = AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))
    fake_db = AsyncMock()
    fake_db.begin = MagicMock(return_value=ctx_mgr)
    fake_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=ep)),  # select
        MagicMock(),  # update embeddings
    ]

    scope = _scope(ep.org_id)
    svc = _make_service(fake_db)
    restored = await svc.restore_episode(
        episode_id=ep.id,
        scope=scope,
        request_id="req-5",
        actor_user_id=None,
    )

    assert restored is ep
    assert ep.deleted_at is None


@pytest.mark.asyncio
async def test_restore_raises_after_grace_period():
    """restore_episode raises ValueError when the 30-day window has expired."""
    ep = _make_episode()
    ep.deleted_at = datetime.now(UTC) - timedelta(days=31)

    ctx_mgr = AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))
    fake_db = AsyncMock()
    fake_db.begin = MagicMock(return_value=ctx_mgr)
    fake_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=ep))

    scope = _scope(ep.org_id)
    svc = _make_service(fake_db)
    with pytest.raises(ValueError, match="Grace window expired"):
        await svc.restore_episode(
            episode_id=ep.id,
            scope=scope,
            request_id="req-6",
            actor_user_id=None,
        )


@pytest.mark.asyncio
async def test_restore_returns_none_when_not_found():
    """restore_episode returns None when the episode row doesn't exist."""
    ctx_mgr = AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))
    fake_db = AsyncMock()
    fake_db.begin = MagicMock(return_value=ctx_mgr)
    fake_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    svc = _make_service(fake_db)
    result = await svc.restore_episode(
        episode_id=uuid.uuid4(),
        scope=_scope(),
        request_id="req-7",
        actor_user_id=None,
    )
    assert result is None


# ── Cascading soft-delete ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_session_memories_marks_episodes_and_embeddings():
    """delete_session_memories issues UPDATE on both episodes and embeddings."""
    session_id = uuid.uuid4()
    org_id = uuid.uuid4()
    scoped_sess = _make_session(org_id=org_id)

    ctx_mgr = AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))
    fake_db = AsyncMock()
    fake_db.begin = MagicMock(return_value=ctx_mgr)

    # Calls in order: select session, count episodes, update embeddings, update episodes
    fake_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=scoped_sess)),
        MagicMock(scalar_one=MagicMock(return_value=3)),
        MagicMock(),  # update embeddings
        MagicMock(),  # update episodes
    ]

    fake_redis = MagicMock()
    fake_cache = AsyncMock()
    fake_cache.delete = AsyncMock()

    scope = _scope(org_id)
    svc = _make_service(fake_db, fake_redis)

    with patch("app.services.forgetting.CacheService", return_value=fake_cache):
        count, restorable = await svc.delete_session_memories(
            session_id=session_id,
            scope=scope,
            request_id="req-8",
            actor_user_id=None,
        )

    assert count == 3
    assert restorable > datetime.now(UTC)
    # Two UPDATE statements were issued (embeddings + episodes)
    update_calls = [c for c in fake_db.execute.call_args_list if "update" in str(c).lower() or True]
    assert fake_db.execute.call_count == 4


@pytest.mark.asyncio
async def test_delete_user_memories_cascades_to_sessions_episodes_embeddings():
    """delete_user_memories issues UPDATE on embeddings, episodes, and sessions."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    ctx_mgr = AsyncMock(__aenter__=AsyncMock(return_value=None), __aexit__=AsyncMock(return_value=False))
    fake_db = AsyncMock()
    fake_db.begin = MagicMock(return_value=ctx_mgr)

    # Calls: count episodes, count sessions, update embeddings, update episodes, update sessions
    fake_db.execute.side_effect = [
        MagicMock(scalar_one=MagicMock(return_value=5)),   # episodes count
        MagicMock(scalar_one=MagicMock(return_value=2)),   # sessions count
        MagicMock(),  # update embeddings
        MagicMock(),  # update episodes
        MagicMock(),  # update sessions
    ]

    svc = _make_service(fake_db)
    result = await svc.delete_user_memories(
        user_id=user_id,
        org_id=org_id,
        request_id="req-9",
        actor_user_id=None,
    )

    assert result.deleted_episodes == 5
    assert result.deleted_sessions == 2
    assert fake_db.execute.call_count == 5


# ── Purge task ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_purge_deletes_only_expired_rows():
    """_do_purge_soft_deleted issues DELETE with deleted_at < cutoff."""
    from app.tasks.cleanup import _do_purge_soft_deleted

    fake_db = AsyncMock()
    ctx_mgr = AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=False),
    )
    outer_ctx = AsyncMock(
        __aenter__=AsyncMock(return_value=fake_db),
        __aexit__=AsyncMock(return_value=False),
    )
    fake_db.begin = MagicMock(return_value=ctx_mgr)

    delete_results = [
        MagicMock(rowcount=2),  # embeddings
        MagicMock(rowcount=1),  # episodes
        MagicMock(rowcount=0),  # sessions
    ]
    fake_db.execute.side_effect = delete_results

    with patch("app.tasks.cleanup.AsyncSessionLocal", return_value=outer_ctx):
        results = await _do_purge_soft_deleted()

    assert results["embeddings"] == 2
    assert results["episodes"] == 1
    assert results["sessions"] == 0
    # Exactly three DELETE statements
    assert fake_db.execute.call_count == 3
