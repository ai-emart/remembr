"""Unified memory query engine for short-term and episodic memory."""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from app.services.episodic import EpisodeSearchResult, EpisodicMemory
from app.services.scoping import MemoryScope
from app.services.search_config import SearchMode, SearchWeights

if TYPE_CHECKING:
    from app.services.short_term import SessionMessage, ShortTermMemory
else:
    SessionMessage = Any
    ShortTermMemory = Any


@dataclass
class MemoryQueryRequest:
    """Inputs that control memory retrieval across all memory layers."""

    query: str | None = None
    session_id: str | None = None
    tags: list[str] | None = None
    from_time: datetime | None = None
    to_time: datetime | None = None
    role: str | None = None
    include_short_term: bool = True
    include_episodic: bool = True
    limit: int = 20
    score_threshold: float = 0.65
    search_mode: SearchMode = "hybrid"
    weights: SearchWeights | None = None


@dataclass
class MemoryQueryResult:
    """Aggregated search output from both memory systems."""

    short_term_messages: list[SessionMessage] = field(default_factory=list)
    episodes: list[EpisodeSearchResult] = field(default_factory=list)
    total_results: int = 0
    query_time_ms: float = 0.0


@dataclass
class _MergedResult:
    kind: Literal["short_term", "episodic"]
    created_at: datetime
    score: float
    payload: SessionMessage | EpisodeSearchResult


class MemoryQueryEngine:
    """Single query entry-point for context-aware memory retrieval."""

    def __init__(self, short_term: ShortTermMemory, episodic: EpisodicMemory) -> None:
        self.short_term = short_term
        self.episodic = episodic

    async def query(self, scope: MemoryScope, request: MemoryQueryRequest) -> MemoryQueryResult:
        """Query short-term and episodic memory concurrently and return merged results."""
        started = time.perf_counter()

        short_task = self._query_short_term(request) if request.include_short_term else None
        episodic_task = self._query_episodic(scope, request) if request.include_episodic else None

        short_results, episodic_results = await asyncio.gather(
            short_task or self._empty_short_term(),
            episodic_task or self._empty_episodic(),
        )

        merged = self._merge_results(short_results, episodic_results, request)
        short_messages = [item.payload for item in merged if item.kind == "short_term"]
        episodes = [item.payload for item in merged if item.kind == "episodic"]

        elapsed_ms = (time.perf_counter() - started) * 1000
        return MemoryQueryResult(
            short_term_messages=short_messages,
            episodes=episodes,
            total_results=len(merged),
            query_time_ms=round(elapsed_ms, 3),
        )

    async def _query_short_term(self, request: MemoryQueryRequest) -> list[SessionMessage]:
        if not request.session_id:
            return []

        messages = await self.short_term.get_context(request.session_id)
        filtered = [msg for msg in messages if self._message_matches(msg, request)]

        return sorted(
            filtered,
            key=lambda msg: (self._message_score(msg, request.query), msg.timestamp),
            reverse=True,
        )[: request.limit]

    async def _query_episodic(
        self,
        scope: MemoryScope,
        request: MemoryQueryRequest,
    ) -> list[EpisodeSearchResult]:
        if request.search_mode == "semantic" and request.query:
            results = await self.episodic.search_semantic(
                scope=scope,
                query=request.query,
                limit=request.limit,
                score_threshold=request.score_threshold,
            )
        elif request.search_mode == "keyword" and request.query:
            results = await self.episodic.search_keyword(
                scope=scope,
                query=request.query,
                tags=request.tags,
                from_time=request.from_time,
                to_time=request.to_time,
                role=request.role,
                session_id=uuid.UUID(request.session_id) if request.session_id else None,
                limit=request.limit,
            )
        elif request.search_mode == "hybrid" and request.query:
            results = await self.episodic.search_hybrid(
                scope=scope,
                query=request.query,
                tags=request.tags,
                from_time=request.from_time,
                to_time=request.to_time,
                role=request.role,
                session_id=uuid.UUID(request.session_id) if request.session_id else None,
                limit=request.limit,
                score_threshold=request.score_threshold,
                weights=request.weights,
            )
        else:
            if request.session_id:
                episodes = await self.episodic.get_session_history(
                    scope=scope,
                    session_id=request.session_id,
                    limit=max(request.limit * 2, request.limit),
                )
            else:
                episodes = await self.episodic.search_by_time(
                    scope=scope,
                    from_time=request.from_time,
                    to_time=request.to_time,
                    limit=max(request.limit * 2, request.limit),
                )

            results = [
                EpisodeSearchResult(episode=episode, similarity_score=0.0) for episode in episodes
            ]

        filtered = [item for item in results if self._episode_matches(item, request)]
        return sorted(
            filtered,
            key=lambda item: (item.similarity_score, item.episode.created_at),
            reverse=True,
        )[: request.limit]

    def _merge_results(
        self,
        short_results: list[SessionMessage],
        episodic_results: list[EpisodeSearchResult],
        request: MemoryQueryRequest,
    ) -> list[_MergedResult]:
        deduped_episodic = self._dedupe_episodic(episodic_results)

        merged: list[_MergedResult] = [
            _MergedResult(
                kind="short_term",
                created_at=msg.timestamp,
                score=self._message_score(msg, request.query),
                payload=msg,
            )
            for msg in short_results
        ]
        merged.extend(
            _MergedResult(
                kind="episodic",
                created_at=item.episode.created_at,
                score=item.similarity_score,
                payload=item,
            )
            for item in deduped_episodic
        )

        merged.sort(key=lambda item: (item.score, item.created_at), reverse=True)

        return merged[: request.limit]

    @staticmethod
    def _dedupe_episodic(results: list[EpisodeSearchResult]) -> list[EpisodeSearchResult]:
        by_episode_id: dict[str, EpisodeSearchResult] = {}
        for result in results:
            episode_id = str(result.episode.id)
            existing = by_episode_id.get(episode_id)
            if existing is None or result.similarity_score > existing.similarity_score:
                by_episode_id[episode_id] = result
        return list(by_episode_id.values())

    @staticmethod
    def _message_matches(message: SessionMessage, request: MemoryQueryRequest) -> bool:
        if request.role and message.role != request.role:
            return False
        if request.from_time and message.timestamp < request.from_time:
            return False
        if request.to_time and message.timestamp > request.to_time:
            return False
        if request.query:
            return request.query.lower() in message.content.lower()
        return True

    @staticmethod
    def _episode_matches(result: EpisodeSearchResult, request: MemoryQueryRequest) -> bool:
        episode = result.episode
        if request.session_id and str(episode.session_id or "") != str(request.session_id):
            return False
        if request.role and episode.role != request.role:
            return False
        if request.tags:
            episode_tags = set(episode.tags or [])
            if episode_tags.isdisjoint(request.tags):
                return False
        if request.from_time and episode.created_at < request.from_time:
            return False
        if request.to_time and episode.created_at > request.to_time:
            return False
        return True

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", text.lower()))

    def _message_score(self, message: SessionMessage, query: str | None) -> float:
        if not query:
            return 0.0
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return 0.0

        content_tokens = self._tokenize(message.content)
        overlap = len(query_tokens.intersection(content_tokens)) / len(query_tokens)
        exact_bonus = 0.2 if query.lower() in message.content.lower() else 0.0
        return overlap + exact_bonus

    async def _empty_short_term(self) -> list[SessionMessage]:
        return []

    async def _empty_episodic(self) -> list[EpisodeSearchResult]:
        return []
