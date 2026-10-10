"""keep the grade job for Oceń ponownie

Revision ID: grading_grade_job
Revises: grading_feedback_pdf
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "grading_grade_job"
down_revision: str | Sequence[str] | None = "grading_feedback_pdf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "submission",
        sa.Column("grade_job", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="grading",
    )


def downgrade() -> None:
    op.drop_column("submission", "grade_job", schema="grading")
