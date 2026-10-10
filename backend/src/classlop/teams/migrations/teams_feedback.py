"""teams feedback: the messages that returned Feedback to Students

Revision ID: teams_feedback
Revises: teams_handins
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "teams_feedback"
down_revision: str | Sequence[str] | None = "teams_handins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("pdf_key", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=True),
        sa.Column("attachment_id", sa.Text(), nullable=True),
        sa.Column("web_url", sa.Text(), nullable=True),
        sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["submission_id"], ["teams.submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "pdf_key"),
        schema="teams",
    )
    op.create_index(
        "ix_teams_feedback_submission_id", "feedback", ["submission_id"], schema="teams"
    )


def downgrade() -> None:
    op.drop_table("feedback", schema="teams")
