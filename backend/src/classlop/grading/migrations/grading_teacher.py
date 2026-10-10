"""teacher actions

Revision ID: grading_teacher
Revises: grading_common_mistakes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "grading_teacher"
down_revision: str | Sequence[str] | None = "grading_common_mistakes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "override",
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("handed_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["submission_id", "handed_in_at", "item_id"],
            ["grading.item.submission_id", "grading.item.handed_in_at", "grading.item.item_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("submission_id", "handed_in_at", "item_id"),
        schema="grading",
    )
    op.add_column(
        "submission",
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        schema="grading",
    )
    op.add_column(
        "submission",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        schema="grading",
    )


def downgrade() -> None:
    op.drop_column("submission", "approved_at", schema="grading")
    op.drop_column("submission", "due_at", schema="grading")
    op.drop_table("override", schema="grading")
