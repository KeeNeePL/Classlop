"""teams attendance fetches, attendees, overrides, links and settings

Revision ID: teams_attendance
Revises: teams_timetable
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "teams_attendance"
down_revision: str | Sequence[str] | None = "teams_timetable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CASCADE = {"ondelete": "CASCADE"}


def _class_id() -> sa.Column:
    return sa.Column("class_id", sa.Text(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "attendance_fetch",
        sa.Column("lesson_id", sa.Text(), nullable=False),
        _class_id(),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["teams.class.id"], **_CASCADE),
        sa.PrimaryKeyConstraint("lesson_id"),
        schema="teams",
    )
    op.create_index(
        "ix_teams_attendance_fetch_class_id", "attendance_fetch", ["class_id"], schema="teams"
    )
    op.create_table(
        "attendee",
        sa.Column("lesson_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        _class_id(),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("first_join", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["teams.class.id"], **_CASCADE),
        sa.PrimaryKeyConstraint("lesson_id", "key"),
        schema="teams",
    )
    op.create_index("ix_teams_attendee_class_id", "attendee", ["class_id"], schema="teams")
    op.create_table(
        "attendance_override",
        sa.Column("lesson_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        _class_id(),
        sa.Column("state", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["teams.class.id"], **_CASCADE),
        sa.ForeignKeyConstraint(["student_id"], ["teams.student.id"], **_CASCADE),
        sa.PrimaryKeyConstraint("lesson_id", "student_id"),
        schema="teams",
    )
    op.create_index(
        "ix_teams_attendance_override_class_id", "attendance_override", ["class_id"], schema="teams"
    )
    op.create_table(
        "attendee_link",
        _class_id(),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["teams.class.id"], **_CASCADE),
        sa.ForeignKeyConstraint(["student_id"], ["teams.student.id"], **_CASCADE),
        sa.PrimaryKeyConstraint("class_id", "key"),
        schema="teams",
    )
    op.create_table(
        "setting",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
        schema="teams",
    )


def downgrade() -> None:
    for table in (
        "setting",
        "attendee_link",
        "attendance_override",
        "attendee",
        "attendance_fetch",
    ):
        op.drop_table(table, schema="teams")
