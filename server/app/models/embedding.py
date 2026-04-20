from __future__ import annotations

"""Embedding model for vector storage."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class Embedding(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """
    Embedding model for storing vector representations.

    Uses pgvector extension for efficient similarity search.
    """

    __tablename__ = "embeddings"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    memory_fact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memory_facts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(
        Vector(),  # variable dimensions — supports all embedding providers
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="embeddings",
    )
    episode: Mapped["Episode | None"] = relationship(
        "Episode",
        back_populates="embeddings",
    )
    memory_fact: Mapped["MemoryFact | None"] = relationship(
        "MemoryFact",
        back_populates="embeddings",
    )

    def __repr__(self) -> str:
        return (
            f"<Embedding(id={self.id}, "
            f"model={self.model}, "
            f"dimensions={self.dimensions}, "
            f"org_id={self.org_id})>"
        )
