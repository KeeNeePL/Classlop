"""teams assignments and their submissions

Revision ID: teams_assignments
Revises: teams_calendar
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "teams_assignments"
down_revision: str | Sequence[str] | None = "teams_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assignment",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("class_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminder_on", sa.Boolean(), nullable=False),
        sa.Column("whole_class", sa.Boolean(), nullable=False),
        sa.Column("item_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("item_versions", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("given_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("give_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_key", sa.Text(), nullable=True),
        sa.Column("post_id", sa.Text(), nullable=True),
        sa.Column("post_channel_id", sa.Text(), nullable=True),
        sa.Column("folder_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["class_id"], ["teams.class.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="teams",
    )
    op.create_index("ix_teams_assignment_class_id", "assignment", ["class_id"], schema="teams")
    op.create_table(
        "submission",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("assignment_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("folder_id", sa.Text(), nullable=True),
        sa.Column("folder_url", sa.Text(), nullable=True),
        sa.Column("permission_id", sa.Text(), nullable=True),
        sa.Column("chat_id", sa.Text(), nullable=True),
        sa.Column("notice_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["assignment_id"], ["teams.assignment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["teams.student.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "student_id"),
        schema="teams",
    )
    op.create_index(
        "ix_teams_submission_assignment_id", "submission", ["assignment_id"], schema="teams"
    )


def downgrade() -> None:
    op.drop_table("submission", schema="teams")
    op.drop_table("assignment", schema="teams")
