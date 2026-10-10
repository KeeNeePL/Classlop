"""common mistakes

Revision ID: grading_common_mistakes
Revises: grading_verification
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "grading_common_mistakes"
down_revision: str | Sequence[str] | None = "grading_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "common_mistake",
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("submission_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("assignment_id", "item_id", "rank"),
        schema="grading",
    )
    op.create_table(
        "common_mistakes_request",
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("assignment_id"),
        schema="grading",
    )
    op.add_column(
        "submission", sa.Column("assignment_id", sa.UUID(), nullable=True), schema="grading"
    )
    op.create_index(
        op.f("ix_grading_submission_assignment_id"),
        "submission",
        ["assignment_id"],
        unique=False,
        schema="grading",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_grading_submission_assignment_id"), table_name="submission", schema="grading"
    )
    op.drop_column("submission", "assignment_id", schema="grading")
    op.drop_table("common_mistakes_request", schema="grading")
    op.drop_table("common_mistake", schema="grading")
