"""Episodic memory service for logging and retrieval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any

from sqlalchemy import ARRAY, DateTime, String, bindparam, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Episode
from app.observability import get_tracer, record_search
from app.repositories import episode_repo
from app.services.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.scoping import MemoryScope
from app.services.search_config import SearchWeights
from app.services.tag_filter import TagFilter, build_tag_filter_sql


@dataclass(frozen=True)
class EpisodeSearchResult:
    """Semantic search result with episode payload and similarity score."""

    episode: Episode
    similarity_score: float


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert str/uuid into UUID or None."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _to_pgvector_literal(vector: list[float]) -> str:
    """Convert a Python float list into pgvector literal format."""
    return "[" + ",".join(str(item) for item in vector) + "]"


def _row_to_episode(row: Any) -> Episode:
    """Build detached Episode model from row mapping."""
    return Episode(
        id=row.id,
        org_id=row.org_id,
        team_id=row.team_id,
        user_id=row.user_id,
        agent_id=row.agent_id,
        session_id=row.session_id,
        role=row.role,
        content=row.content,
        tags=row.tags,
        metadata_=row.metadata,
        created_at=row.created_at,
    )


class EpisodicMemory:
    """High-level episodic memory service backed by Celery for embedding generation."""

    def __init__(
        self,
        db: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.db = db

    @property
    def _provider(self) -> EmbeddingProvider:
        return get_embedding_provider()

    async def _finalize_search(
        self,
        *,
        scope: MemoryScope,
        mode: str,
        started_at: float,
        rows: Any,
    ) -> list[EpisodeSearchResult]:
        record_search(scope.org_id, mode, (perf_counter() - started_at) * 1000)
        return [
            EpisodeSearchResult(
                episode=_row_to_episode(row),
                similarity_score=float(row.similarity_score),
            )
            for row in rows
        ]

    async def log(
        self,
        scope: MemoryScope,
        role: str,
        content: str,
        tags: list[str] | None = None,
        session_id: str | uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Episode:
        """Persist an episode and dispatch a Celery task to generate its embedding."""
        episode = await episode_repo.log_episode(
            db=self.db,
            scope=scope,
            role=role,
            content=content,
            tags=tags or [],
            metadata=metadata or {},
            session_id=session_id,
        )

        from app.tasks.embeddings import generate_embedding_for_episode

        generate_embedding_for_episode.delay(str(episode.id))
        return episode

    async def search_by_tags(
        self,
        scope: MemoryScope,
        tags: list[str],
        limit: int = 20,
    ) -> list[Episode]:
        """Return episodes whose tags overlap the provided set."""
        return await episode_repo.list_episodes(
            db=self.db,
            scope=scope,
            tags=tags,
            limit=limit,
        )

    async def search_by_time(
        self,
        scope: MemoryScope,
        from_time: datetime | None,
        to_time: datetime | None,
        limit: int = 50,
    ) -> list[Episode]:
        """Return episodes constrained to a time range."""
        return await episode_repo.list_episodes(
            db=self.db,
            scope=scope,
            from_time=from_time,
            to_time=to_time,
            limit=limit,
        )

    async def get_session_history(
        self,
        scope: MemoryScope,
        session_id: str | uuid.UUID,
        limit: int = 100,
    ) -> list[Episode]:
        """Return recent session episodes in descending creation order."""
        return await episode_repo.list_episodes(
            db=self.db,
            scope=scope,
            session_id=session_id,
            limit=limit,
        )

    async def replay_session(
        self,
        scope: MemoryScope,
        session_id: str | uuid.UUID,
    ) -> list[Episode]:
        """Return full session history ordered oldest-to-newest."""
        history = await episode_repo.list_episodes(
            db=self.db,
            scope=scope,
            session_id=session_id,
            limit=10_000,
        )
        return sorted(history, key=lambda ep: ep.created_at)

    async def delete(self, scope: MemoryScope, episode_id: str | uuid.UUID) -> None:
        """Delete an episode in scope."""
        await episode_repo.delete_episode(
            db=self.db,
            episode_id=episode_id,
            scope=scope,
        )

    async def search_semantic(
        self,
        scope: MemoryScope,
        query: str,
        limit: int = 10,
        score_threshold: float = 0.7,
        tag_filters: list[TagFilter] | None = None,
    ) -> list[EpisodeSearchResult]:
        """Run semantic search against episode embeddings within scope."""
        tracer = get_tracer("app.services.episodic")
        started_at = perf_counter()
        with tracer.start_as_current_span(
            "memory.search",
            attributes={
                "mode": "semantic",
                "query_length": len(query),
                "limit": limit,
            },
        ):
            query_vector, _ = await self._provider.generate_embedding(query)
            vector_literal = _to_pgvector_literal(query_vector)

            tf_sql, tf_params = build_tag_filter_sql(tag_filters or [], alias="e")
            tf_clause = f"\n              AND {tf_sql}" if tf_sql else ""

            sql = text(
                f"""
            SELECT
                e.id,
                e.org_id,
                e.team_id,
                e.user_id,
                e.agent_id,
                e.session_id,
                e.role,
                e.content,
                e.tags,
                e.metadata,
                e.created_at,
                1 - (emb.vector <=> '{vector_literal}'::vector) AS similarity_score
            FROM embeddings emb
            JOIN episodes e ON e.id = emb.episode_id
            WHERE e.org_id = :org_id
              AND e.team_id IS NOT DISTINCT FROM :team_id
              AND e.user_id IS NOT DISTINCT FROM :user_id
              AND e.agent_id IS NOT DISTINCT FROM :agent_id
              AND e.deleted_at IS NULL
              AND emb.deleted_at IS NULL
              AND 1 - (emb.vector <=> '{vector_literal}'::vector) >= :score_threshold{tf_clause}
            ORDER BY similarity_score DESC
            LIMIT :limit
            """
            )
            result = await self.db.execute(
                sql,
                {
                    "org_id": _as_uuid(scope.org_id),
                    "team_id": _as_uuid(scope.team_id),
                    "user_id": _as_uuid(scope.user_id),
                    "agent_id": _as_uuid(scope.agent_id),
                    "score_threshold": score_threshold,
                    "limit": limit,
                    **tf_params,
                },
            )
            return await self._finalize_search(
                scope=scope,
                mode="semantic",
                started_at=started_at,
                rows=result,
            )

    async def search_hybrid(
        self,
        scope: MemoryScope,
        query: str,
        tags: list[str] | None = None,
        tag_filters: list[TagFilter] | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        role: str | None = None,
        session_id: uuid.UUID | None = None,
        limit: int = 10,
        score_threshold: float = 0.65,
        weights: SearchWeights | None = None,
    ) -> list[EpisodeSearchResult]:
        """Run one-roundtrip semantic + keyword + recency search using a CTE."""
        tracer = get_tracer("app.services.episodic")
        started_at = perf_counter()
        with tracer.start_as_current_span(
            "memory.search",
            attributes={
                "mode": "hybrid",
                "query_length": len(query),
                "limit": limit,
            },
        ):
            resolved_weights = weights or SearchWeights()
            query_vector, _ = await self._provider.generate_embedding(query)
            vector_literal = _to_pgvector_literal(query_vector)

            tf_sql, tf_params = build_tag_filter_sql(tag_filters or [], alias="e")
            tf_clause = f"\n              AND {tf_sql}" if tf_sql else ""

            sql = text(
                f"""
            WITH filtered_episodes AS (
                SELECT
                    e.id,
                    e.org_id,
                    e.team_id,
                    e.user_id,
                    e.agent_id,
                    e.session_id,
                    e.role,
                    e.content,
                    e.tags,
                    e.metadata,
                    e.created_at,
                    e.search_vector
                FROM episodes e
                WHERE e.org_id = :org_id
                  AND e.team_id IS NOT DISTINCT FROM :team_id
                  AND e.user_id IS NOT DISTINCT FROM :user_id
                  AND e.agent_id IS NOT DISTINCT FROM :agent_id
                  AND e.deleted_at IS NULL
                  AND (
                      CAST(:tags AS VARCHAR[]) IS NULL
                      OR e.tags && CAST(:tags AS VARCHAR[])
                  )
                  AND (
                      CAST(:from_time AS TIMESTAMPTZ) IS NULL
                      OR e.created_at >= CAST(:from_time AS TIMESTAMPTZ)
                  )
                  AND (
                      CAST(:to_time AS TIMESTAMPTZ) IS NULL
                      OR e.created_at <= CAST(:to_time AS TIMESTAMPTZ)
                  )
                  AND (
                      CAST(:role AS VARCHAR) IS NULL
                      OR e.role = CAST(:role AS VARCHAR)
                  )
                  AND (
                      CAST(:session_id AS UUID) IS NULL
                      OR e.session_id = CAST(:session_id AS UUID)
                  ){tf_clause}
            ),
            keyword_query AS (
                SELECT plainto_tsquery('english', :query) AS ts_query
            ),
            semantic_candidates AS (
                SELECT
                    fe.id AS episode_id,
                    1 - (emb.vector <=> '{vector_literal}'::vector) AS similarity_score
                FROM embeddings emb
                JOIN filtered_episodes fe ON fe.id = emb.episode_id
                WHERE emb.org_id = :org_id
                  AND emb.deleted_at IS NULL
                  AND 1 - (emb.vector <=> '{vector_literal}'::vector) >= :score_threshold
                ORDER BY similarity_score DESC
                LIMIT 50
            ),
            keyword_candidates AS (
                SELECT
                    fe.id AS episode_id,
                    ts_rank_cd(fe.search_vector, kq.ts_query) AS bm25_score
                FROM filtered_episodes fe
                CROSS JOIN keyword_query kq
                WHERE kq.ts_query <> ''::tsquery
                  AND fe.search_vector @@ kq.ts_query
                ORDER BY bm25_score DESC
                LIMIT 50
            ),
            candidate_ids AS (
                SELECT episode_id FROM semantic_candidates
                UNION
                SELECT episode_id FROM keyword_candidates
            )
            SELECT
                fe.id,
                fe.org_id,
                fe.team_id,
                fe.user_id,
                fe.agent_id,
                fe.session_id,
                fe.role,
                fe.content,
                fe.tags,
                fe.metadata,
                fe.created_at,
                (
                    COALESCE(sc.similarity_score, 0.0) * :semantic_weight
                    + COALESCE(kc.bm25_score, 0.0) * :keyword_weight
                    + LEAST(
                        1.0,
                        GREATEST(
                            0.0,
                            EXP(
                                -(
                                    EXTRACT(EPOCH FROM (NOW() - fe.created_at)) / 3600.0
                                ) / 168.0
                            )
                        )
                    ) * :recency_weight
                ) AS similarity_score
            FROM candidate_ids ci
            JOIN filtered_episodes fe ON fe.id = ci.episode_id
            LEFT JOIN semantic_candidates sc ON sc.episode_id = fe.id
            LEFT JOIN keyword_candidates kc ON kc.episode_id = fe.id
            ORDER BY similarity_score DESC, fe.created_at DESC
            LIMIT :limit
            """
            ).bindparams(
                bindparam("tags", type_=ARRAY(String())),
                bindparam("from_time", type_=DateTime(timezone=True)),
                bindparam("to_time", type_=DateTime(timezone=True)),
                bindparam("role", type_=String()),
                bindparam("session_id", type_=UUID(as_uuid=True)),
            )
            result = await self.db.execute(
                sql,
                {
                    "org_id": _as_uuid(scope.org_id),
                    "team_id": _as_uuid(scope.team_id),
                    "user_id": _as_uuid(scope.user_id),
                    "agent_id": _as_uuid(scope.agent_id),
                    "score_threshold": score_threshold,
                    "tags": tags,
                    "from_time": from_time,
                    "to_time": to_time,
                    "role": role,
                    "session_id": session_id,
                    "limit": limit,
                    "query": query,
                    "semantic_weight": resolved_weights.semantic,
                    "keyword_weight": resolved_weights.keyword,
                    "recency_weight": resolved_weights.recency,
                    **tf_params,
                },
            )
            return await self._finalize_search(
                scope=scope,
                mode="hybrid",
                started_at=started_at,
                rows=result,
            )

    async def search_keyword(
        self,
        scope: MemoryScope,
        query: str,
        tags: list[str] | None = None,
        tag_filters: list[TagFilter] | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        role: str | None = None,
        session_id: uuid.UUID | None = None,
        limit: int = 10,
    ) -> list[EpisodeSearchResult]:
        """Run full-text keyword search against episode content within scope."""
        tracer = get_tracer("app.services.episodic")
        started_at = perf_counter()
        with tracer.start_as_current_span(
            "memory.search",
            attributes={
                "mode": "keyword",
                "query_length": len(query),
                "limit": limit,
            },
        ):
            tf_sql, tf_params = build_tag_filter_sql(tag_filters or [], alias="e")
            tf_clause = f"\n              AND {tf_sql}" if tf_sql else ""

            sql = text(
                f"""
            WITH keyword_query AS (
                SELECT plainto_tsquery('english', :query) AS ts_query
            )
            SELECT
                e.id,
                e.org_id,
                e.team_id,
                e.user_id,
                e.agent_id,
                e.session_id,
                e.role,
                e.content,
                e.tags,
                e.metadata,
                e.created_at,
                ts_rank_cd(e.search_vector, kq.ts_query) AS similarity_score
            FROM episodes e
            CROSS JOIN keyword_query kq
            WHERE e.org_id = :org_id
              AND e.team_id IS NOT DISTINCT FROM :team_id
              AND e.user_id IS NOT DISTINCT FROM :user_id
              AND e.agent_id IS NOT DISTINCT FROM :agent_id
              AND e.deleted_at IS NULL
              AND (
                  CAST(:tags AS VARCHAR[]) IS NULL
                  OR e.tags && CAST(:tags AS VARCHAR[])
              )
              AND (
                  CAST(:from_time AS TIMESTAMPTZ) IS NULL
                  OR e.created_at >= CAST(:from_time AS TIMESTAMPTZ)
              )
              AND (
                  CAST(:to_time AS TIMESTAMPTZ) IS NULL
                  OR e.created_at <= CAST(:to_time AS TIMESTAMPTZ)
              )
              AND (CAST(:role AS VARCHAR) IS NULL OR e.role = CAST(:role AS VARCHAR))
              AND (
                  CAST(:session_id AS UUID) IS NULL
                  OR e.session_id = CAST(:session_id AS UUID)
              )
              AND kq.ts_query <> ''::tsquery
              AND e.search_vector @@ kq.ts_query{tf_clause}
            ORDER BY similarity_score DESC, e.created_at DESC
            LIMIT :limit
            """
            ).bindparams(
                bindparam("tags", type_=ARRAY(String())),
                bindparam("from_time", type_=DateTime(timezone=True)),
                bindparam("to_time", type_=DateTime(timezone=True)),
                bindparam("role", type_=String()),
                bindparam("session_id", type_=UUID(as_uuid=True)),
            )
            result = await self.db.execute(
                sql,
                {
                    "org_id": _as_uuid(scope.org_id),
                    "team_id": _as_uuid(scope.team_id),
                    "user_id": _as_uuid(scope.user_id),
                    "agent_id": _as_uuid(scope.agent_id),
                    "query": query,
                    "tags": tags,
                    "from_time": from_time,
                    "to_time": to_time,
                    "role": role,
                    "session_id": session_id,
                    "limit": limit,
                    **tf_params,
                },
            )
            return await self._finalize_search(
                scope=scope,
                mode="keyword",
                started_at=started_at,
                rows=result,
            )

    async def reconstruct_state_at(
        self,
        scope: MemoryScope,
        timestamp: datetime,
    ) -> list[Episode]:
        """Return all scoped episodes that existed at a given timestamp."""
        snapshot = await episode_repo.list_episodes(
            db=self.db,
            scope=scope,
            to_time=timestamp,
            limit=10_000,
        )
        return sorted(snapshot, key=lambda ep: ep.created_at)
