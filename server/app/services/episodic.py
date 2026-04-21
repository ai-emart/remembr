"""Episodic memory service for logging and retrieval."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Episode
from app.repositories import episode_repo
from app.services.embeddings import EmbeddingProvider, get_embedding_provider
from app.services.scoping import MemoryScope
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

        return [
            EpisodeSearchResult(
                episode=_row_to_episode(row),
                similarity_score=float(row.similarity_score),
            )
            for row in result
        ]

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
    ) -> list[EpisodeSearchResult]:
        """Run one-roundtrip semantic + metadata search using a CTE."""
        query_vector, _ = await self._provider.generate_embedding(query)
        vector_literal = _to_pgvector_literal(query_vector)

        tf_sql, tf_params = build_tag_filter_sql(tag_filters or [], alias="e")
        tf_clause = f"\n              AND {tf_sql}" if tf_sql else ""

        sql = text(
            f"""
            WITH semantic_candidates AS (
                SELECT
                    emb.episode_id,
                    1 - (emb.vector <=> '{vector_literal}'::vector) AS similarity_score
                FROM embeddings emb
                WHERE emb.org_id = :org_id
                  AND emb.deleted_at IS NULL
                  AND 1 - (emb.vector <=> '{vector_literal}'::vector) >= :score_threshold
                ORDER BY similarity_score DESC
                LIMIT 50
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
                sc.similarity_score
            FROM semantic_candidates sc
            JOIN episodes e ON e.id = sc.episode_id
            WHERE e.org_id = :org_id
              AND e.team_id IS NOT DISTINCT FROM :team_id
              AND e.user_id IS NOT DISTINCT FROM :user_id
              AND e.agent_id IS NOT DISTINCT FROM :agent_id
              AND e.deleted_at IS NULL
              AND (:tags IS NULL OR e.tags && :tags)
              AND (:from_time IS NULL OR e.created_at >= :from_time)
              AND (:to_time IS NULL OR e.created_at <= :to_time)
              AND (:role IS NULL OR e.role = :role)
              AND (:session_id IS NULL OR e.session_id = :session_id){tf_clause}
            ORDER BY sc.similarity_score DESC
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
                "tags": tags,
                "from_time": from_time,
                "to_time": to_time,
                "role": role,
                "session_id": session_id,
                "limit": limit,
                **tf_params,
            },
        )

        return [
            EpisodeSearchResult(
                episode=_row_to_episode(row),
                similarity_score=float(row.similarity_score),
            )
            for row in result
        ]

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
