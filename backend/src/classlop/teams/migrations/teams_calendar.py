"""teams calendar sync: series, occurrences and the delta cursor

Revision ID: teams_calendar
Revises: teams_timetable_edits
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "teams_calendar"
down_revision: str | Sequence[str] | None = "teams_timetable_edits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_series",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("class_id", sa.Text(), nullable=True),
        sa.Column("candidates", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["teams.class.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="teams",
    )
    op.create_index(
        "ix_teams_calendar_series_class_id", "calendar_series", ["class_id"], schema="teams"
    )
    op.create_table(
        "calendar_event",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("series_id", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("join_url", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["series_id"], ["teams.calendar_series.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="teams",
    )
    op.create_index(
        "ix_teams_calendar_event_series_id", "calendar_event", ["series_id"], schema="teams"
    )
    op.create_table(
        "calendar_cursor",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("delta_link", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="teams",
    )


def downgrade() -> None:
    op.drop_table("calendar_cursor", schema="teams")
    op.drop_table("calendar_event", schema="teams")
    op.drop_table("calendar_series", schema="teams")
