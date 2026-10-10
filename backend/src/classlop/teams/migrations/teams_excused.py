"""teams excused: the Teacher's private reason on an Excused Submission

Revision ID: teams_excused
Revises: teams_feedback
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "teams_excused"
down_revision: str | Sequence[str] | None = "teams_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "submission", sa.Column("excused_reason", sa.Text(), nullable=True), schema="teams"
    )


def downgrade() -> None:
    op.drop_column("submission", "excused_reason", schema="teams")
