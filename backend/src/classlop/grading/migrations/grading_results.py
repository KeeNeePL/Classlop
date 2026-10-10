"""grading results

Revision ID: grading_results
Revises: grading_base
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "grading_results"
down_revision: str | Sequence[str] | None = "grading_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "submission",
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("handed_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("held_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("spot_check_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'graded', 'failed')", name="submission_status"
        ),
        sa.PrimaryKeyConstraint("submission_id", "handed_in_at"),
        schema="grading",
    )
    op.create_table(
        "item",
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("handed_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("max_points", sa.Integer(), nullable=False),
        sa.Column("ai_points", sa.Integer(), nullable=False),
        sa.Column("reading", sa.Text(), nullable=False),
        sa.Column("drawing", sa.Boolean(), nullable=False),
        sa.Column("ai_transcription", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "reading IN ('readable', 'unsure', 'unreadable', 'blank')", name="item_reading"
        ),
        sa.ForeignKeyConstraint(
            ["submission_id", "handed_in_at"],
            ["grading.submission.submission_id", "grading.submission.handed_in_at"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("submission_id", "handed_in_at", "item_id"),
        schema="grading",
    )


def downgrade() -> None:
    op.drop_table("item", schema="grading")
    op.drop_table("submission", schema="grading")
