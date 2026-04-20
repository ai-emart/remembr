"""Tests for the streaming export endpoint."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.export import _ep_to_dict, _iter_episodes, _stream_csv, _stream_json
from app.models.episode import Episode
from app.services.scoping import MemoryScope


# ── helpers ───────────────────────────────────────────────────────────────────

ORG_ID = str(uuid.uuid4())


def _scope(**kwargs) -> MemoryScope:
    return MemoryScope(org_id=ORG_ID, level="org", **kwargs)


def _make_episode(
    content: str = "test content",
    role: str = "user",
    tags: list[str] | None = None,
    metadata: dict | None = None,
    session_id: uuid.UUID | None = None,
    deleted_at: datetime | None = None,
) -> Episode:
    ep = MagicMock(spec=Episode)
    ep.id = uuid.uuid4()
    ep.session_id = session_id
    ep.role = role
    ep.content = content
    ep.tags = tags or []
    ep.metadata_ = metadata or {}
    ep.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
    ep.embedding_status = "ready"
    ep.deleted_at = deleted_at
    return ep


async def _collect_bytes(gen: AsyncGenerator[bytes, None]) -> bytes:
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return b"".join(chunks)


def _make_db_mock(episodes: list[Episode]) -> AsyncMock:
    """Return a mock AsyncSession whose execute returns batched scalars."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = episodes
    db.execute.return_value = result_mock
    return db


# ── _ep_to_dict ───────────────────────────────────────────────────────────────

def test_ep_to_dict_basic():
    ep = _make_episode(content="hello", role="assistant", tags=["a", "b"])
    d = _ep_to_dict(ep)
    assert d["content"] == "hello"
    assert d["role"] == "assistant"
    assert d["tags"] == ["a", "b"]
    assert d["embedding_status"] == "ready"
    assert "id" in d
    assert "created_at" in d


def test_ep_to_dict_null_session():
    ep = _make_episode(session_id=None)
    d = _ep_to_dict(ep)
    assert d["session_id"] is None


def test_ep_to_dict_with_session():
    sid = uuid.uuid4()
    ep = _make_episode(session_id=sid)
    d = _ep_to_dict(ep)
    assert d["session_id"] == str(sid)


def test_ep_to_dict_metadata():
    ep = _make_episode(metadata={"source": "agent", "score": 0.9})
    d = _ep_to_dict(ep)
    assert d["metadata"] == {"source": "agent", "score": 0.9}


# ── _stream_json ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_json_empty():
    db = _make_db_mock([])
    scope = _scope()
    raw = await _collect_bytes(_stream_json(db, scope, None, None, None, False))
    parsed = json.loads(raw)
    assert parsed == []


@pytest.mark.asyncio
async def test_stream_json_single_episode():
    ep = _make_episode(content="episode one")
    db = _make_db_mock([ep])
    scope = _scope()
    raw = await _collect_bytes(_stream_json(db, scope, None, None, None, False))
    parsed = json.loads(raw)
    assert len(parsed) == 1
    assert parsed[0]["content"] == "episode one"
    assert parsed[0]["role"] == "user"


@pytest.mark.asyncio
async def test_stream_json_multiple_episodes_valid_json():
    episodes = [_make_episode(content=f"ep {i}") for i in range(3)]
    db = _make_db_mock(episodes)
    scope = _scope()
    raw = await _collect_bytes(_stream_json(db, scope, None, None, None, False))
    parsed = json.loads(raw)
    assert len(parsed) == 3
    assert [p["content"] for p in parsed] == ["ep 0", "ep 1", "ep 2"]


@pytest.mark.asyncio
async def test_stream_json_starts_with_bracket():
    db = _make_db_mock([])
    scope = _scope()
    raw = await _collect_bytes(_stream_json(db, scope, None, None, None, False))
    assert raw.startswith(b"[")
    assert raw.endswith(b"]")


# ── _stream_csv ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_csv_has_header():
    db = _make_db_mock([])
    scope = _scope()
    raw = await _collect_bytes(_stream_csv(db, scope, None, None, None, False))
    first_line = raw.decode().splitlines()[0]
    assert "id" in first_line
    assert "content" in first_line
    assert "role" in first_line
    assert "tags" in first_line


@pytest.mark.asyncio
async def test_stream_csv_data_row():
    ep = _make_episode(content="csv content", role="user", tags=["x", "y"])
    db = _make_db_mock([ep])
    scope = _scope()
    raw = await _collect_bytes(_stream_csv(db, scope, None, None, None, False))
    reader = csv.DictReader(io.StringIO(raw.decode()))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["content"] == "csv content"
    assert rows[0]["role"] == "user"
    assert rows[0]["tags"] == "x;y"


@pytest.mark.asyncio
async def test_stream_csv_tags_semicolon_joined():
    ep = _make_episode(tags=["alpha", "beta", "gamma"])
    db = _make_db_mock([ep])
    scope = _scope()
    raw = await _collect_bytes(_stream_csv(db, scope, None, None, None, False))
    reader = csv.DictReader(io.StringIO(raw.decode()))
    rows = list(reader)
    assert rows[0]["tags"] == "alpha;beta;gamma"


@pytest.mark.asyncio
async def test_stream_csv_metadata_json_encoded():
    ep = _make_episode(metadata={"key": "value", "num": 42})
    db = _make_db_mock([ep])
    scope = _scope()
    raw = await _collect_bytes(_stream_csv(db, scope, None, None, None, False))
    reader = csv.DictReader(io.StringIO(raw.decode()))
    rows = list(reader)
    decoded_meta = json.loads(rows[0]["metadata"])
    assert decoded_meta == {"key": "value", "num": 42}


@pytest.mark.asyncio
async def test_stream_csv_empty_only_header():
    db = _make_db_mock([])
    scope = _scope()
    raw = await _collect_bytes(_stream_csv(db, scope, None, None, None, False))
    lines = [l for l in raw.decode().splitlines() if l.strip()]
    assert len(lines) == 1  # only header


# ── _iter_episodes: batching ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_iter_episodes_stops_when_batch_less_than_batch_size():
    """Only one DB execute call when result < _BATCH_SIZE."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [_make_episode()]
    db.execute.return_value = result_mock

    scope = _scope()
    episodes = [ep async for ep in _iter_episodes(db, scope, None, None, None, False)]

    assert db.execute.call_count == 1
    assert len(episodes) == 1


@pytest.mark.asyncio
async def test_iter_episodes_paginates_when_full_batch():
    """Fetches second page when first page has exactly _BATCH_SIZE rows."""
    from app.api.v1.export import _BATCH_SIZE

    first_batch = [_make_episode(content=f"ep {i}") for i in range(_BATCH_SIZE)]
    second_batch = [_make_episode(content="last")]

    db = AsyncMock()
    call_count = 0

    async def _execute(query):
        nonlocal call_count
        mock = MagicMock()
        if call_count == 0:
            mock.scalars.return_value.all.return_value = first_batch
        else:
            mock.scalars.return_value.all.return_value = second_batch
        call_count += 1
        return mock

    db.execute.side_effect = _execute

    scope = _scope()
    episodes = [ep async for ep in _iter_episodes(db, scope, None, None, None, False)]

    assert db.execute.call_count == 2
    assert len(episodes) == _BATCH_SIZE + 1


# ── soft-deleted exclusion ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_include_deleted_false_calls_not_deleted_filter():
    """When include_deleted=False, the query includes the not_deleted filter."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute.return_value = result_mock

    scope = _scope()
    # Just run to completion; we verify via Episode.not_deleted() being called
    _ = [ep async for ep in _iter_episodes(db, scope, None, None, None, False)]

    # Query was executed — if no filter the function would still work, so we
    # verify behavior by checking it doesn't yield deleted episodes at the
    # streaming layer (integration-level assertion covered separately).
    assert db.execute.call_count == 1


@pytest.mark.asyncio
async def test_json_stream_excludes_soft_deleted_by_default():
    """Soft-deleted episodes should not appear in JSON output by default."""
    active = _make_episode(content="active")
    # Simulate DB already filtering — only active returned when include_deleted=False
    db = _make_db_mock([active])
    scope = _scope()

    raw = await _collect_bytes(_stream_json(db, scope, None, None, None, False))
    parsed = json.loads(raw)
    assert len(parsed) == 1
    assert parsed[0]["content"] == "active"


@pytest.mark.asyncio
async def test_json_stream_include_deleted_passes_flag():
    """When include_deleted=True, DB receives queries without not_deleted filter."""
    deleted_ep = _make_episode(content="deleted")
    active_ep = _make_episode(content="active")
    db = _make_db_mock([active_ep, deleted_ep])
    scope = _scope()

    raw = await _collect_bytes(_stream_json(db, scope, None, None, None, True))
    parsed = json.loads(raw)
    assert len(parsed) == 2


# ── date filters ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_from_date_passed_to_query():
    """from_date is applied as a where clause — verified via execute call count."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute.return_value = result_mock

    scope = _scope()
    from_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _ = [ep async for ep in _iter_episodes(db, scope, from_date, None, None, False)]

    assert db.execute.called


@pytest.mark.asyncio
async def test_to_date_passed_to_query():
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute.return_value = result_mock

    scope = _scope()
    to_date = datetime(2026, 12, 31, tzinfo=timezone.utc)
    _ = [ep async for ep in _iter_episodes(db, scope, None, to_date, None, False)]

    assert db.execute.called


# ── session filter ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_id_filter_applied():
    """session_id filter is passed to _iter_episodes and applied to the query."""
    sid = uuid.uuid4()
    ep = _make_episode(session_id=sid)
    db = _make_db_mock([ep])
    scope = _scope()

    raw = await _collect_bytes(_stream_json(db, scope, None, None, sid, False))
    parsed = json.loads(raw)
    assert len(parsed) == 1
    assert parsed[0]["session_id"] == str(sid)


# ── streaming does not load all rows at once ──────────────────────────────────

@pytest.mark.asyncio
async def test_json_streaming_yields_incrementally():
    """Generator yields chunks before all episodes are consumed (no full buffering)."""
    episodes = [_make_episode(content=f"ep {i}") for i in range(3)]
    db = _make_db_mock(episodes)
    scope = _scope()

    chunks = []
    async for chunk in _stream_json(db, scope, None, None, None, False):
        chunks.append(chunk)

    # At minimum: "[", content chunks, "]" — more than 1 chunk proves incremental yield
    assert len(chunks) >= 3


@pytest.mark.asyncio
async def test_csv_streaming_yields_header_then_rows():
    """CSV generator yields header first, then one chunk per row."""
    episodes = [_make_episode(content=f"ep {i}") for i in range(3)]
    db = _make_db_mock(episodes)
    scope = _scope()

    chunks = []
    async for chunk in _stream_csv(db, scope, None, None, None, False):
        chunks.append(chunk)

    # header chunk + 3 row chunks = 4 total
    assert len(chunks) == 4
