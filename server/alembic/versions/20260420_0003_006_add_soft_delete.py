"""Add deleted_at soft-delete column to episodes, sessions, and embeddings.

Revision ID: 006
Revises: 005
Create Date: 2026-04-20 00:03:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("episodes", "sessions", "embeddings"):
        op.add_column(
            table,
            sa.Column(
                "deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=None,
            ),
        )
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])


def downgrade() -> None:
    for table in ("episodes", "sessions", "embeddings"):
        op.drop_index(f"ix_{table}_deleted_at", table_name=table)
        op.drop_column(table, "deleted_at")
