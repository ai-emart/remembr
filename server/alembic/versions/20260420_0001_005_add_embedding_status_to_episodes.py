"""Add embedding_status, embedding_generated_at, embedding_error to episodes.
Backfill: episodes with an existing embedding → 'ready'; others → 'pending'.
Also relax the vector column from vector(1024) to vector (variable dimensions)
to support embedding providers other than Jina AI.

Revision ID: 005
Revises: 004
Create Date: 2026-04-20 00:01:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── New columns ──────────────────────────────────────────────────────────
    op.add_column(
        "episodes",
        sa.Column(
            "embedding_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "episodes",
        sa.Column(
            "embedding_generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "episodes",
        sa.Column("embedding_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_episodes_embedding_status",
        "episodes",
        ["embedding_status"],
    )

    # ── Backfill ─────────────────────────────────────────────────────────────
    # Episodes that already have an embedding row become 'ready'
    op.execute(
        """
        UPDATE episodes e
        SET embedding_status       = 'ready',
            embedding_generated_at = emb.created_at
        FROM embeddings emb
        WHERE emb.episode_id = e.id
        """
    )

    # ── Relax vector column dimensions ───────────────────────────────────────
    # Remove the hard-coded 1024-dimension constraint so that providers
    # returning different dimensions (Ollama: 768, ST: 384) can be stored.
    op.execute("ALTER TABLE embeddings ALTER COLUMN vector TYPE vector")


def downgrade() -> None:
    op.drop_index("ix_episodes_embedding_status", table_name="episodes")
    op.drop_column("episodes", "embedding_error")
    op.drop_column("episodes", "embedding_generated_at")
    op.drop_column("episodes", "embedding_status")
    # Note: reverting the vector column type change is intentionally omitted —
    # narrowing back to vector(1024) would reject any non-1024-dim rows already stored.
