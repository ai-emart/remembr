"""Repository functions for episodic interaction storage and retrieval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Episode
from app.services.scoping import MemoryScope


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert incoming ids to UUID for SQLAlchemy filters."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _apply_scope_filters(query: Select[Any], scope: MemoryScope) -> Select[Any]:
    """Apply exact scope boundary filtering for episode access (excludes soft-deleted)."""
    return (
        query.where(Episode.org_id == _as_uuid(scope.org_id))
        .where(Episode.team_id == _as_uuid(scope.team_id))
        .where(Episode.user_id == _as_uuid(scope.user_id))
        .where(Episode.agent_id == _as_uuid(scope.agent_id))
        .where(Episode.not_deleted())
    )


async def log_episode(
    db: AsyncSession,
    scope: MemoryScope,
    role: str,
    content: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | uuid.UUID | None = None,
) -> Episode:
    """Persist a new episode in the provided scope."""
    episode = Episode(
        org_id=_as_uuid(scope.org_id),
        team_id=_as_uuid(scope.team_id),
        user_id=_as_uuid(scope.user_id),
        agent_id=_as_uuid(scope.agent_id),
        session_id=_as_uuid(session_id),
        role=role,
        content=content,
        tags=tags or [],
        metadata_=metadata or {},
    )
    db.add(episode)
    await db.flush()
    await db.refresh(episode)
    return episode


async def get_episode(
    db: AsyncSession,
    episode_id: str | uuid.UUID,
    scope: MemoryScope,
) -> Episode | None:
    """Get a non-deleted episode by id if it belongs to the provided scope."""
    query = select(Episode).where(Episode.id == _as_uuid(episode_id))
    query = _apply_scope_filters(query, scope)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def list_episodes(
    db: AsyncSession,
    scope: MemoryScope,
    session_id: str | uuid.UUID | None = None,
    tags: list[str] | None = None,
    role: str | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Episode]:
    """List non-deleted episodes in scope with optional session/tag/role/time filtering."""
    query = select(Episode)
    query = _apply_scope_filters(query, scope)

    if session_id is not None:
        query = query.where(Episode.session_id == _as_uuid(session_id))
    if tags:
        query = query.where(Episode.tags.op("&&")(tags))
    if role:
        query = query.where(Episode.role == role)
    if from_time:
        query = query.where(Episode.created_at >= from_time)
    if to_time:
        query = query.where(Episode.created_at <= to_time)

    query = query.order_by(Episode.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def delete_episode(
    db: AsyncSession,
    episode_id: str | uuid.UUID,
    scope: MemoryScope,
) -> None:
    """Soft-delete an episode if it exists in scope."""
    episode = await get_episode(db, episode_id, scope)
    if episode is None:
        return

    episode.deleted_at = datetime.now(UTC)
    await db.flush()


async def count_episodes(db: AsyncSession, scope: MemoryScope) -> int:
    """Count non-deleted episodes available in the provided scope."""
    query = select(func.count(Episode.id))
    query = _apply_scope_filters(query, scope)
    result = await db.execute(query)
    return int(result.scalar_one())
