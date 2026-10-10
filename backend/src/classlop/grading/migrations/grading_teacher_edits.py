"""Transcription fix and Feedback edit

Revision ID: grading_teacher_edits
Revises: grading_grade_job
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "grading_teacher_edits"
down_revision: str | Sequence[str] | None = "grading_grade_job"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "item", sa.Column("fixed_transcription", sa.Text(), nullable=True), schema="grading"
    )
    op.add_column("item", sa.Column("edited_feedback", sa.Text(), nullable=True), schema="grading")


def downgrade() -> None:
    op.drop_column("item", "edited_feedback", schema="grading")
    op.drop_column("item", "fixed_transcription", schema="grading")
