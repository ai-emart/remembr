"""Add full-text search vector to episodes.

Revision ID: 007
Revises: 006
Create Date: 2026-04-21 00:04:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

SEARCH_VECTOR_FUNCTION = "episodes_search_vector_update"
SEARCH_VECTOR_TRIGGER = "trg_episodes_search_vector"
SEARCH_VECTOR_INDEX = "ix_episodes_search_vector"


def upgrade() -> None:
    op.add_column(
        "episodes",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            nullable=True,
            server_default=None,
        ),
    )

    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {SEARCH_VECTOR_FUNCTION}() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector := to_tsvector('english', COALESCE(NEW.content, ''));
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {SEARCH_VECTOR_TRIGGER}
            BEFORE INSERT OR UPDATE OF content ON episodes
            FOR EACH ROW
            EXECUTE FUNCTION {SEARCH_VECTOR_FUNCTION}();
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE episodes
            SET search_vector = to_tsvector('english', COALESCE(content, ''))
            """
        )
    )
    op.create_index(
        SEARCH_VECTOR_INDEX,
        "episodes",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(SEARCH_VECTOR_INDEX, table_name="episodes")
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS {SEARCH_VECTOR_TRIGGER} ON episodes"))
    op.execute(sa.text(f"DROP FUNCTION IF EXISTS {SEARCH_VECTOR_FUNCTION}()"))
    op.drop_column("episodes", "search_vector")
