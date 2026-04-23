"""Repository functions for session CRUD operations."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session
from app.services.scoping import MemoryScope


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Convert id values to UUID for model filtering."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _apply_scope_filters(query: Any, scope: MemoryScope) -> Any:
    """Apply exact scope filtering for session access (excludes soft-deleted)."""
    return (
        query.where(Session.org_id == _as_uuid(scope.org_id))
        .where(Session.team_id == _as_uuid(scope.team_id))
        .where(Session.user_id == _as_uuid(scope.user_id))
        .where(Session.agent_id == _as_uuid(scope.agent_id))
        .where(Session.not_deleted())
    )


async def create_session(
    db: AsyncSession,
    scope: MemoryScope,
    metadata: dict[str, Any] | None,
) -> Session:
    """Create a session in the provided scope."""
    session = Session(
        org_id=_as_uuid(scope.org_id),
        team_id=_as_uuid(scope.team_id),
        user_id=_as_uuid(scope.user_id),
        agent_id=_as_uuid(scope.agent_id),
        metadata_=metadata,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def get_session(
    db: AsyncSession,
    session_id: str | uuid.UUID,
    scope: MemoryScope,
) -> Session | None:
    """Get a non-deleted session by id if it matches scope."""
    query = select(Session).where(Session.id == _as_uuid(session_id))
    query = _apply_scope_filters(query, scope)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def update_session(
    db: AsyncSession,
    session_id: str | uuid.UUID,
    metadata: dict[str, Any] | None,
) -> Session:
    """Update session metadata."""
    result = await db.execute(
        select(Session).where(Session.id == _as_uuid(session_id)).where(Session.not_deleted())
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise ValueError(f"Session not found: {session_id}")

    session.metadata_ = metadata
    await db.flush()
    await db.refresh(session)
    return session


async def list_sessions(
    db: AsyncSession,
    scope: MemoryScope,
    limit: int = 20,
    offset: int = 0,
) -> list[Session]:
    """List non-deleted sessions in scope ordered by recent update."""
    query = select(Session).order_by(Session.updated_at.desc()).limit(limit).offset(offset)
    query = _apply_scope_filters(query, scope)
    result = await db.execute(query)
    return list(result.scalars().all())


async def delete_session(
    db: AsyncSession,
    session_id: str | uuid.UUID,
    scope: MemoryScope,
) -> None:
    """Soft-delete a session if it matches scope."""
    session = await get_session(db, session_id, scope)
    if session is None:
        return
    session.deleted_at = datetime.now(UTC)
    await db.flush()
