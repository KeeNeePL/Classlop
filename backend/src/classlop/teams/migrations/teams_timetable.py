"""teams timetable slots and single lessons

Revision ID: teams_timetable
Revises: teams_classes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "teams_timetable"
down_revision: str | Sequence[str] | None = "teams_classes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("class", sa.Column("school_year_end", sa.Date(), nullable=True), schema="teams")
    op.create_table(
        "timetable_slot",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("class_id", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("first_on", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["teams.class.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="teams",
    )
    op.create_index(
        "ix_teams_timetable_slot_class_id", "timetable_slot", ["class_id"], schema="teams"
    )
    op.create_table(
        "lesson",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("class_id", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["teams.class.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="teams",
    )
    op.create_index("ix_teams_lesson_class_id", "lesson", ["class_id"], schema="teams")


def downgrade() -> None:
    op.drop_table("lesson", schema="teams")
    op.drop_table("timetable_slot", schema="teams")
    op.drop_column("class", "school_year_end", schema="teams")
