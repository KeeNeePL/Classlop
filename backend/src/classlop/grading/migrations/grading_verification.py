"""grading verification

Revision ID: grading_verification
Revises: grading_feedback
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "grading_verification"
down_revision: str | Sequence[str] | None = "grading_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "item", sa.Column("verification_note", sa.Text(), nullable=True), schema="grading"
    )


def downgrade() -> None:
    op.drop_column("item", "verification_note", schema="grading")
