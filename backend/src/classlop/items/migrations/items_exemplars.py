"""items exemplars: the Knowledge base

Revision ID: items_exemplars
Revises: items_records
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "items_exemplars"
down_revision: str | Sequence[str] | None = "items_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "exemplar",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("solution", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.Text(), nullable=False),
        sa.Column("curriculum_topics", JSONB, nullable=False),
        sa.Column("general_requirements", JSONB, nullable=False),
        sa.Column("source_tags", JSONB, nullable=False),
        sa.Column("embedding", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="exemplar_difficulty"),
        sa.PrimaryKeyConstraint("id"),
        schema="items",
    )


def downgrade() -> None:
    op.drop_table("exemplar", schema="items")
