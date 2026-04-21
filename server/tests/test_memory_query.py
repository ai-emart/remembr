"""Unit tests for unified memory query engine."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.episodic import EpisodeSearchResult
from app.services.memory_query import MemoryQueryEngine, MemoryQueryRequest
from app.services.scoping import MemoryScope
from app.services.search_config import SearchWeights


class _FakeShortTerm:
    def __init__(self, messages: list[SimpleNamespace], delay: float = 0.0):
        self.messages = messages
        self.delay = delay

    async def get_context(self, _session_id: str) -> list[SimpleNamespace]:
        if self.delay:
            await asyncio.sleep(self.delay)
        return list(self.messages)


class _FakeEpisodic:
    def __init__(self, results: list[EpisodeSearchResult], delay: float = 0.0):
        self.results = results
        self.delay = delay
        self.calls: list[tuple[str, dict]] = []

    async def search_semantic(self, **_kwargs):
        self.calls.append(("semantic", _kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        return list(self.results)

    async def search_keyword(self, **_kwargs):
        self.calls.append(("keyword", _kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        return list(self.results)

    async def search_hybrid(self, **_kwargs):
        self.calls.append(("hybrid", _kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        return list(self.results)

    async def search_by_time(self, **_kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        return [item.episode for item in self.results]

    async def get_session_history(self, **_kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        return [item.episode for item in self.results]


@pytest.fixture
def scope() -> MemoryScope:
    return MemoryScope(org_id=str(uuid.uuid4()), level="org")


@pytest.mark.asyncio
async def test_query_runs_short_term_and_episodic_concurrently(scope: MemoryScope):
    now = datetime.now(UTC)
    short = _FakeShortTerm(
        messages=[
            SimpleNamespace(
                role="user",
                content="Need ideas for dinner",
                tokens=4,
                priority_score=1.0,
                timestamp=now,
            )
        ],
        delay=0.15,
    )
    session_id = str(uuid.uuid4())
    episode = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        role="assistant",
        tags=["food"],
        created_at=now,
    )
    episodic = _FakeEpisodic(
        results=[EpisodeSearchResult(episode=episode, similarity_score=0.9)],
        delay=0.15,
    )

    engine = MemoryQueryEngine(short_term=short, episodic=episodic)
    req = MemoryQueryRequest(query="dinner", session_id=session_id, search_mode="hybrid")

    started = asyncio.get_running_loop().time()
    result = await engine.query(scope, req)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.25
    assert result.total_results == 2
    assert result.query_time_ms > 0


@pytest.mark.asyncio
async def test_query_dedupes_episodes_and_merges_by_relevance(scope: MemoryScope):
    now = datetime.now(UTC)
    short = _FakeShortTerm(
        messages=[
            SimpleNamespace(
                role="assistant",
                content="Reset password from account settings",
                tokens=6,
                priority_score=1.0,
                timestamp=now - timedelta(seconds=5),
            )
        ]
    )

    duplicate_episode_id = uuid.uuid4()
    top_episode = SimpleNamespace(
        id=duplicate_episode_id,
        session_id=str(uuid.uuid4()),
        role="assistant",
        tags=["support"],
        created_at=now - timedelta(seconds=10),
    )
    lower_duplicate = SimpleNamespace(
        id=duplicate_episode_id,
        session_id=top_episode.session_id,
        role="assistant",
        tags=["support"],
        created_at=now - timedelta(minutes=2),
    )
    episodic = _FakeEpisodic(
        results=[
            EpisodeSearchResult(episode=lower_duplicate, similarity_score=0.71),
            EpisodeSearchResult(episode=top_episode, similarity_score=0.95),
        ]
    )

    engine = MemoryQueryEngine(short_term=short, episodic=episodic)
    req = MemoryQueryRequest(
        query="reset password",
        session_id=top_episode.session_id,
        limit=5,
        search_mode="hybrid",
    )

    result = await engine.query(scope, req)

    assert len(result.episodes) == 1
    assert result.episodes[0].similarity_score == pytest.approx(0.95)
    assert result.total_results == 2
    assert result.episodes[0].episode.id == duplicate_episode_id


@pytest.mark.asyncio
async def test_query_dispatches_keyword_mode(scope: MemoryScope):
    now = datetime.now(UTC)
    episode = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=None,
        role="assistant",
        tags=["ops"],
        created_at=now,
    )
    episodic = _FakeEpisodic(results=[EpisodeSearchResult(episode=episode, similarity_score=0.8)])
    engine = MemoryQueryEngine(short_term=_FakeShortTerm(messages=[]), episodic=episodic)

    result = await engine.query(scope, MemoryQueryRequest(query="ERR_1234", search_mode="keyword"))

    assert len(result.episodes) == 1
    assert episodic.calls[0][0] == "keyword"


@pytest.mark.asyncio
async def test_query_passes_hybrid_weights(scope: MemoryScope):
    now = datetime.now(UTC)
    episode = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=None,
        role="assistant",
        tags=["ops"],
        created_at=now,
    )
    episodic = _FakeEpisodic(results=[EpisodeSearchResult(episode=episode, similarity_score=0.77)])
    engine = MemoryQueryEngine(short_term=_FakeShortTerm(messages=[]), episodic=episodic)
    weights = SearchWeights(semantic=0.2, keyword=0.3, recency=0.5)

    await engine.query(
        scope,
        MemoryQueryRequest(query="billing retry", search_mode="hybrid", weights=weights),
    )

    assert episodic.calls[0][0] == "hybrid"
    assert episodic.calls[0][1]["weights"] == weights
