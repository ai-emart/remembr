from __future__ import annotations

"""Episode model."""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

EMBEDDING_STATUS_PENDING = "pending"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_FAILED = "failed"

from app.db.base import Base, SoftDeleteMixin, UUIDMixin


class Episode(Base, UUIDMixin, SoftDeleteMixin):
    """
    Episode model representing individual messages or interactions.

    Episodes are the atomic units of memory in the system.
    """

    __tablename__ = "episodes"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        nullable=True,
        server_default=None,
    )
    tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    embedding_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EMBEDDING_STATUS_PENDING,
        server_default=EMBEDDING_STATUS_PENDING,
        index=True,
    )
    embedding_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    embedding_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="episodes",
    )
    team: Mapped["Team | None"] = relationship(
        "Team",
        back_populates="episodes",
    )
    user: Mapped["User | None"] = relationship(
        "User",
        back_populates="episodes",
    )
    agent: Mapped["Agent | None"] = relationship(
        "Agent",
        back_populates="episodes",
    )
    session: Mapped["Session | None"] = relationship(
        "Session",
        back_populates="episodes",
    )
    memory_facts: Mapped[list["MemoryFact"]] = relationship(
        "MemoryFact",
        back_populates="source_episode",
    )
    embeddings: Mapped[list["Embedding"]] = relationship(
        "Embedding",
        back_populates="episode",
        cascade="all, delete-orphan",
    )
    embedding: Mapped["Embedding | None"] = relationship(
        "Embedding",
        back_populates="episode",
        uselist=False,
        overlaps="embeddings",
    )

    def __repr__(self) -> str:
        return f"<Episode(id={self.id}, role={self.role}, org_id={self.org_id})>"
