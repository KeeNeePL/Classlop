"""summary, Do powtórki and the Feedback PDF

Revision ID: grading_feedback_pdf
Revises: grading_teacher
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "grading_feedback_pdf"
down_revision: str | Sequence[str] | None = "grading_teacher"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "submission",
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        schema="grading",
    )
    op.add_column("submission", sa.Column("pdf_key", sa.Text(), nullable=True), schema="grading")
    op.add_column(
        "item",
        sa.Column(
            "curriculum_topics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema="grading",
    )


def downgrade() -> None:
    op.drop_column("item", "curriculum_topics", schema="grading")
    op.drop_column("submission", "pdf_key", schema="grading")
    op.drop_column("submission", "summary", schema="grading")
