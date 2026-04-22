"""Tests for forgetting service transactional delete flows."""

from __future__ import annotations

import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

if "tiktoken" not in sys.modules:
    fake_tiktoken = types.ModuleType("tiktoken")
    fake_tiktoken.get_encoding = lambda _name: SimpleNamespace(encode=lambda _text: [1])
    sys.modules["tiktoken"] = fake_tiktoken

os.environ.setdefault("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/remembr_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("JINA_API_KEY", "test-jina-key")

from app.services.forgetting import ForgettingService
from app.services.scoping import MemoryScope


@pytest.mark.asyncio
async def test_delete_episode_writes_success_audit(monkeypatch):
    db = Mock()
    redis = AsyncMock()

    begin_cm = AsyncMock()
    begin_cm.__aenter__.return_value = None
    begin_cm.__aexit__.return_value = False
    db.begin.return_value = begin_cm

    episode_id = uuid4()
    scope = MemoryScope(org_id=str(uuid4()), user_id=str(uuid4()), level="user")

    fake_episode = SimpleNamespace(id=episode_id, deleted_at=None)
    db.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(scalar_one_or_none=lambda: fake_episode),
            SimpleNamespace(),  # update embeddings
        ]
    )
    db.delete = AsyncMock()

    svc = ForgettingService(db=db, redis=redis, session_factory=lambda: AsyncMock())
    svc._write_audit = AsyncMock()

    result = await svc.delete_episode(
        episode_id=episode_id,
        scope=scope,
        request_id="req-1",
        actor_user_id=None,
    )

    assert result.deleted is True
    assert result.soft is True
    assert svc._write_audit.await_count == 1
    assert svc._write_audit.await_args.kwargs["status"] == "success"


@pytest.mark.asyncio
async def test_delete_user_memories_logs_attempt_and_failure(monkeypatch):
    db = Mock()
    redis = AsyncMock()

    begin_cm = AsyncMock()
    begin_cm.__aenter__.side_effect = RuntimeError("tx fail")
    begin_cm.__aexit__.return_value = False
    db.begin.return_value = begin_cm

    svc = ForgettingService(db=db, redis=redis, session_factory=lambda: AsyncMock())
    svc._write_audit = AsyncMock()

    with pytest.raises(RuntimeError):
        await svc.delete_user_memories(
            user_id=uuid4(),
            org_id=uuid4(),
            request_id="req-2",
            actor_user_id=None,
        )

    statuses = [call.kwargs["status"] for call in svc._write_audit.await_args_list]
    assert "attempt" in statuses
    assert "failed" in statuses
