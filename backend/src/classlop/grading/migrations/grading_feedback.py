"""grading feedback

Revision ID: grading_feedback
Revises: grading_results
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "grading_feedback"
down_revision: str | Sequence[str] | None = "grading_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Defaults only fill the rows graded before this revision.
    op.add_column(
        "item",
        sa.Column("doubt", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="grading",
    )
    op.add_column(
        "item",
        sa.Column("feedback", sa.Text(), server_default="", nullable=False),
        schema="grading",
    )
    op.add_column("item", sa.Column("mistake", sa.Text(), nullable=True), schema="grading")


def downgrade() -> None:
    op.drop_column("item", "mistake", schema="grading")
    op.drop_column("item", "feedback", schema="grading")
    op.drop_column("item", "doubt", schema="grading")
