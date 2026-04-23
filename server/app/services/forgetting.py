"""Forgetting service for GDPR-compliant memory deletion workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import AsyncSessionLocal
from app.models import AuditLog, Embedding, Episode, Session
from app.observability import record_memory_deleted
from app.services.cache import CacheService, make_key
from app.services.events import emit_event_safely
from app.services.scoping import MemoryScope

SOFT_DELETE_GRACE_DAYS = 30


@dataclass
class SoftDeleteResult:
    deleted: bool
    soft: bool
    restorable_until: datetime | None


@dataclass
class UserDeleteResult:
    deleted_episodes: int
    deleted_sessions: int


class ForgettingService:
    """Service for memory/session/user erasure with audit trails."""

    def __init__(
        self,
        db: AsyncSession,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.db = db
        self.redis = redis
        self.session_factory = session_factory or AsyncSessionLocal

    @staticmethod
    def _scope_query_filters(scope: MemoryScope) -> dict[str, UUID | None]:
        return {
            "org_id": UUID(scope.org_id),
            "team_id": UUID(scope.team_id) if scope.team_id else None,
            "user_id": UUID(scope.user_id) if scope.user_id else None,
            "agent_id": UUID(scope.agent_id) if scope.agent_id else None,
        }

    async def _write_audit(
        self,
        *,
        action: str,
        status: str,
        target_type: str,
        target_id: str | None,
        request_id: str,
        actor_user_id: UUID | None,
        org_id: UUID | None,
        details: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        try:
            async with self.session_factory() as audit_db:
                audit_db.add(
                    AuditLog(
                        org_id=org_id,
                        actor_user_id=actor_user_id,
                        action=action,
                        status=status,
                        target_type=target_type,
                        target_id=target_id,
                        request_id=request_id,
                        details=details,
                        error_message=error_message,
                    )
                )
                await audit_db.commit()
        except Exception as exc:
            logger.error("Failed to persist audit log", action=action, error=str(exc))

    # ── Soft deletes ──────────────────────────────────────────────────────────

    async def delete_episode(
        self,
        *,
        episode_id: UUID,
        scope: MemoryScope,
        request_id: str,
        actor_user_id: UUID | None,
    ) -> SoftDeleteResult:
        """Soft-delete an episode and its embeddings. Returns restorable_until."""
        try:
            filters = self._scope_query_filters(scope)
            async with self.db.begin():
                result = await self.db.execute(
                    select(Episode)
                    .where(Episode.id == episode_id)
                    .where(Episode.org_id == filters["org_id"])
                    .where(Episode.team_id == filters["team_id"])
                    .where(Episode.user_id == filters["user_id"])
                    .where(Episode.agent_id == filters["agent_id"])
                    .where(Episode.not_deleted())
                )
                episode = result.scalar_one_or_none()
                if episode is None:
                    return SoftDeleteResult(deleted=False, soft=False, restorable_until=None)

                now = datetime.now(UTC)
                episode.deleted_at = now

                await self.db.execute(
                    update(Embedding)
                    .where(Embedding.episode_id == episode_id)
                    .where(Embedding.deleted_at.is_(None))
                    .values(deleted_at=now)
                )

            restorable_until = now + timedelta(days=SOFT_DELETE_GRACE_DAYS)
            await self._write_audit(
                action="soft_delete_episode",
                status="success",
                target_type="episode",
                target_id=str(episode_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=filters["org_id"],
                details={"restorable_until": restorable_until.isoformat()},
            )
            await emit_event_safely(
                event_name="memory.deleted",
                payload={
                    "delete_mode": "soft",
                    "scope": "episode",
                    "episode_id": str(episode_id),
                    "org_id": str(filters["org_id"]),
                    "restorable_until": restorable_until.isoformat(),
                },
                org_id=filters["org_id"],
            )
            record_memory_deleted(str(filters["org_id"]), 1)
            return SoftDeleteResult(deleted=True, soft=True, restorable_until=restorable_until)
        except Exception as exc:
            await self._write_audit(
                action="soft_delete_episode",
                status="failed",
                target_type="episode",
                target_id=str(episode_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=UUID(scope.org_id),
                error_message=str(exc),
            )
            raise

    async def delete_session_memories(
        self,
        *,
        session_id: UUID,
        scope: MemoryScope,
        request_id: str,
        actor_user_id: UUID | None,
    ) -> tuple[int, datetime]:
        """Soft-delete all episodes (and their embeddings) within a session.

        The session record itself is preserved. Returns (count, restorable_until).
        """
        filters = self._scope_query_filters(scope)
        try:
            async with self.db.begin():
                session_result = await self.db.execute(
                    select(Session)
                    .where(Session.id == session_id)
                    .where(Session.org_id == filters["org_id"])
                    .where(Session.team_id == filters["team_id"])
                    .where(Session.user_id == filters["user_id"])
                    .where(Session.agent_id == filters["agent_id"])
                    .where(Session.not_deleted())
                )
                scoped_session = session_result.scalar_one_or_none()
                if scoped_session is None:
                    return 0, datetime.now(UTC) + timedelta(days=SOFT_DELETE_GRACE_DAYS)

                count_result = await self.db.execute(
                    select(func.count(Episode.id))
                    .where(Episode.session_id == session_id)
                    .where(Episode.not_deleted())
                )
                deleted_count = int(count_result.scalar_one())

                now = datetime.now(UTC)

                await self.db.execute(
                    update(Embedding)
                    .where(
                        Embedding.episode_id.in_(
                            select(Episode.id).where(
                                Episode.session_id == session_id,
                                Episode.deleted_at.is_(None),
                            )
                        )
                    )
                    .where(Embedding.deleted_at.is_(None))
                    .values(deleted_at=now)
                )
                await self.db.execute(
                    update(Episode)
                    .where(Episode.session_id == session_id)
                    .where(Episode.deleted_at.is_(None))
                    .values(deleted_at=now)
                )

                cache = CacheService(self.redis)
                await cache.delete(make_key("short_term", str(session_id), "window"))

            restorable_until = now + timedelta(days=SOFT_DELETE_GRACE_DAYS)
            await self._write_audit(
                action="soft_delete_session_memories",
                status="success",
                target_type="session",
                target_id=str(session_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=filters["org_id"],
                details={
                    "deleted_count": deleted_count,
                    "restorable_until": restorable_until.isoformat(),
                },
            )
            await emit_event_safely(
                event_name="memory.deleted",
                payload={
                    "delete_mode": "soft",
                    "scope": "session",
                    "session_id": str(session_id),
                    "org_id": str(filters["org_id"]),
                    "deleted_count": deleted_count,
                    "restorable_until": restorable_until.isoformat(),
                },
                org_id=filters["org_id"],
            )
            record_memory_deleted(str(filters["org_id"]), deleted_count)
            return deleted_count, restorable_until
        except Exception as exc:
            await self._write_audit(
                action="soft_delete_session_memories",
                status="failed",
                target_type="session",
                target_id=str(session_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=UUID(scope.org_id),
                error_message=str(exc),
            )
            raise

    async def delete_user_memories(
        self,
        *,
        user_id: UUID,
        org_id: UUID,
        request_id: str,
        actor_user_id: UUID | None,
    ) -> UserDeleteResult:
        """Soft-delete all sessions, episodes, and embeddings for a user."""
        await self._write_audit(
            action="soft_delete_user_memories",
            status="attempt",
            target_type="user",
            target_id=str(user_id),
            request_id=request_id,
            actor_user_id=actor_user_id,
            org_id=org_id,
        )

        try:
            now = datetime.now(UTC)
            async with self.db.begin():
                episodes_count_result = await self.db.execute(
                    select(func.count(Episode.id))
                    .where(Episode.org_id == org_id)
                    .where(Episode.user_id == user_id)
                    .where(Episode.not_deleted())
                )
                deleted_episodes = int(episodes_count_result.scalar_one())

                sessions_count_result = await self.db.execute(
                    select(func.count(Session.id))
                    .where(Session.org_id == org_id)
                    .where(Session.user_id == user_id)
                    .where(Session.not_deleted())
                )
                deleted_sessions = int(sessions_count_result.scalar_one())

                await self.db.execute(
                    update(Embedding)
                    .where(
                        Embedding.episode_id.in_(
                            select(Episode.id)
                            .where(Episode.org_id == org_id)
                            .where(Episode.user_id == user_id)
                        )
                    )
                    .where(Embedding.deleted_at.is_(None))
                    .values(deleted_at=now)
                )
                await self.db.execute(
                    update(Episode)
                    .where(Episode.org_id == org_id)
                    .where(Episode.user_id == user_id)
                    .where(Episode.deleted_at.is_(None))
                    .values(deleted_at=now)
                )
                await self.db.execute(
                    update(Session)
                    .where(Session.org_id == org_id)
                    .where(Session.user_id == user_id)
                    .where(Session.deleted_at.is_(None))
                    .values(deleted_at=now)
                )

            restorable_until = now + timedelta(days=SOFT_DELETE_GRACE_DAYS)
            await self._write_audit(
                action="soft_delete_user_memories",
                status="success",
                target_type="user",
                target_id=str(user_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=org_id,
                details={
                    "deleted_episodes": deleted_episodes,
                    "deleted_sessions": deleted_sessions,
                    "restorable_until": restorable_until.isoformat(),
                },
            )
            await emit_event_safely(
                event_name="memory.deleted",
                payload={
                    "delete_mode": "soft",
                    "scope": "user",
                    "user_id": str(user_id),
                    "org_id": str(org_id),
                    "deleted_episodes": deleted_episodes,
                    "deleted_sessions": deleted_sessions,
                    "restorable_until": restorable_until.isoformat(),
                },
                org_id=org_id,
            )
            record_memory_deleted(str(org_id), deleted_episodes)

            return UserDeleteResult(
                deleted_episodes=deleted_episodes,
                deleted_sessions=deleted_sessions,
            )
        except Exception as exc:
            await self._write_audit(
                action="soft_delete_user_memories",
                status="failed",
                target_type="user",
                target_id=str(user_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=org_id,
                error_message=str(exc),
            )
            raise

    # ── Hard deletes ──────────────────────────────────────────────────────────

    async def hard_delete_episode(
        self,
        *,
        episode_id: UUID,
        scope: MemoryScope,
        request_id: str,
        actor_user_id: UUID | None,
    ) -> bool:
        """Immediately hard-delete an episode (bypasses 30-day grace period).

        Enterprise-gated: caller identity is always persisted in the audit log.
        """
        filters = self._scope_query_filters(scope)
        try:
            async with self.db.begin():
                result = await self.db.execute(
                    select(Episode)
                    .where(Episode.id == episode_id)
                    .where(Episode.org_id == filters["org_id"])
                    .where(Episode.team_id == filters["team_id"])
                    .where(Episode.user_id == filters["user_id"])
                    .where(Episode.agent_id == filters["agent_id"])
                )
                episode = result.scalar_one_or_none()
                if episode is None:
                    return False

                await self.db.execute(delete(Embedding).where(Embedding.episode_id == episode_id))
                await self.db.delete(episode)

            logger.warning(
                "Hard-deleted episode",
                episode_id=str(episode_id),
                actor=str(actor_user_id),
                request_id=request_id,
            )
            await self._write_audit(
                action="hard_delete_episode",
                status="success",
                target_type="episode",
                target_id=str(episode_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=filters["org_id"],
                details={"actor": str(actor_user_id)},
            )
            await emit_event_safely(
                event_name="memory.deleted",
                payload={
                    "delete_mode": "hard",
                    "scope": "episode",
                    "episode_id": str(episode_id),
                    "org_id": str(filters["org_id"]),
                },
                org_id=filters["org_id"],
            )
            record_memory_deleted(str(filters["org_id"]), 1)
            return True
        except Exception as exc:
            await self._write_audit(
                action="hard_delete_episode",
                status="failed",
                target_type="episode",
                target_id=str(episode_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=UUID(scope.org_id),
                error_message=str(exc),
            )
            raise

    async def hard_delete_session_memories(
        self,
        *,
        session_id: UUID,
        scope: MemoryScope,
        request_id: str,
        actor_user_id: UUID | None,
    ) -> int:
        """Immediately hard-delete all episodes+embeddings in a session.

        Enterprise-gated: caller identity is always persisted in the audit log.
        """
        filters = self._scope_query_filters(scope)
        try:
            async with self.db.begin():
                session_result = await self.db.execute(
                    select(Session)
                    .where(Session.id == session_id)
                    .where(Session.org_id == filters["org_id"])
                    .where(Session.team_id == filters["team_id"])
                    .where(Session.user_id == filters["user_id"])
                    .where(Session.agent_id == filters["agent_id"])
                )
                if session_result.scalar_one_or_none() is None:
                    return 0

                count_result = await self.db.execute(
                    select(func.count(Episode.id)).where(Episode.session_id == session_id)
                )
                deleted_count = int(count_result.scalar_one())

                await self.db.execute(
                    delete(Embedding).where(
                        Embedding.episode_id.in_(
                            select(Episode.id).where(Episode.session_id == session_id)
                        )
                    )
                )
                await self.db.execute(delete(Episode).where(Episode.session_id == session_id))

                cache = CacheService(self.redis)
                await cache.delete(make_key("short_term", str(session_id), "window"))

            logger.warning(
                "Hard-deleted session memories",
                session_id=str(session_id),
                count=deleted_count,
                actor=str(actor_user_id),
                request_id=request_id,
            )
            await self._write_audit(
                action="hard_delete_session_memories",
                status="success",
                target_type="session",
                target_id=str(session_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=filters["org_id"],
                details={"deleted_count": deleted_count, "actor": str(actor_user_id)},
            )
            await emit_event_safely(
                event_name="memory.deleted",
                payload={
                    "delete_mode": "hard",
                    "scope": "session",
                    "session_id": str(session_id),
                    "org_id": str(filters["org_id"]),
                    "deleted_count": deleted_count,
                },
                org_id=filters["org_id"],
            )
            record_memory_deleted(str(filters["org_id"]), deleted_count)
            return deleted_count
        except Exception as exc:
            await self._write_audit(
                action="hard_delete_session_memories",
                status="failed",
                target_type="session",
                target_id=str(session_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=UUID(scope.org_id),
                error_message=str(exc),
            )
            raise

    async def hard_delete_user_memories(
        self,
        *,
        user_id: UUID,
        org_id: UUID,
        request_id: str,
        actor_user_id: UUID | None,
    ) -> UserDeleteResult:
        """Immediately hard-delete all sessions, episodes, and embeddings for a user.

        Enterprise-gated: caller identity is always persisted in the audit log.
        """
        await self._write_audit(
            action="hard_delete_user_memories",
            status="attempt",
            target_type="user",
            target_id=str(user_id),
            request_id=request_id,
            actor_user_id=actor_user_id,
            org_id=org_id,
            details={"actor": str(actor_user_id)},
        )
        try:
            async with self.db.begin():
                session_ids_result = await self.db.execute(
                    select(Session.id)
                    .where(Session.org_id == org_id)
                    .where(Session.user_id == user_id)
                )
                session_ids = [row[0] for row in session_ids_result.all()]

                episodes_count_result = await self.db.execute(
                    select(func.count(Episode.id))
                    .where(Episode.org_id == org_id)
                    .where(Episode.user_id == user_id)
                )
                deleted_episodes = int(episodes_count_result.scalar_one())
                deleted_sessions = len(session_ids)

                if session_ids:
                    await self.db.execute(
                        delete(Embedding).where(
                            Embedding.episode_id.in_(
                                select(Episode.id).where(Episode.session_id.in_(session_ids))
                            )
                        )
                    )

                await self.db.execute(
                    delete(Embedding)
                    .where(Embedding.org_id == org_id)
                    .where(
                        Embedding.episode_id.in_(
                            select(Episode.id)
                            .where(Episode.org_id == org_id)
                            .where(Episode.user_id == user_id)
                        )
                    )
                )
                await self.db.execute(
                    delete(Episode)
                    .where(Episode.org_id == org_id)
                    .where(Episode.user_id == user_id)
                )
                await self.db.execute(
                    delete(Session)
                    .where(Session.org_id == org_id)
                    .where(Session.user_id == user_id)
                )

            logger.warning(
                "Hard-deleted user memories",
                user_id=str(user_id),
                episodes=deleted_episodes,
                sessions=deleted_sessions,
                actor=str(actor_user_id),
                request_id=request_id,
            )
            await self._write_audit(
                action="hard_delete_user_memories",
                status="success",
                target_type="user",
                target_id=str(user_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=org_id,
                details={
                    "deleted_episodes": deleted_episodes,
                    "deleted_sessions": deleted_sessions,
                    "actor": str(actor_user_id),
                },
            )
            await emit_event_safely(
                event_name="memory.deleted",
                payload={
                    "delete_mode": "hard",
                    "scope": "user",
                    "user_id": str(user_id),
                    "org_id": str(org_id),
                    "deleted_episodes": deleted_episodes,
                    "deleted_sessions": deleted_sessions,
                },
                org_id=org_id,
            )
            record_memory_deleted(str(org_id), deleted_episodes)
            return UserDeleteResult(
                deleted_episodes=deleted_episodes,
                deleted_sessions=deleted_sessions,
            )
        except Exception as exc:
            await self._write_audit(
                action="hard_delete_user_memories",
                status="failed",
                target_type="user",
                target_id=str(user_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=org_id,
                error_message=str(exc),
            )
            raise

    # ── Restore ───────────────────────────────────────────────────────────────

    async def restore_episode(
        self,
        *,
        episode_id: UUID,
        scope: MemoryScope,
        request_id: str,
        actor_user_id: UUID | None,
    ) -> Episode | None:
        """Restore a soft-deleted episode if within the 30-day grace window.

        Returns the episode on success, None if the row does not exist at all,
        or raises ValueError if the window has expired.
        """
        filters = self._scope_query_filters(scope)
        try:
            async with self.db.begin():
                result = await self.db.execute(
                    select(Episode)
                    .where(Episode.id == episode_id)
                    .where(Episode.org_id == filters["org_id"])
                    .where(Episode.team_id == filters["team_id"])
                    .where(Episode.user_id == filters["user_id"])
                    .where(Episode.agent_id == filters["agent_id"])
                )
                episode = result.scalar_one_or_none()
                if episode is None:
                    return None

                if episode.deleted_at is None:
                    return episode

                cutoff = datetime.now(UTC) - timedelta(days=SOFT_DELETE_GRACE_DAYS)
                if episode.deleted_at < cutoff:
                    raise ValueError(
                        f"Grace window expired: deleted_at={episode.deleted_at.isoformat()}"
                    )

                episode.deleted_at = None
                await self.db.execute(
                    update(Embedding)
                    .where(Embedding.episode_id == episode_id)
                    .values(deleted_at=None)
                )

            await self._write_audit(
                action="restore_episode",
                status="success",
                target_type="episode",
                target_id=str(episode_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=filters["org_id"],
            )
            return episode
        except ValueError:
            raise
        except Exception as exc:
            await self._write_audit(
                action="restore_episode",
                status="failed",
                target_type="episode",
                target_id=str(episode_id),
                request_id=request_id,
                actor_user_id=actor_user_id,
                org_id=UUID(scope.org_id),
                error_message=str(exc),
            )
            raise
