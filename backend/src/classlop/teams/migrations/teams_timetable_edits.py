"""teams timetable edits: replaced slots and occurrence topics

Revision ID: teams_timetable_edits
Revises: teams_timetable
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "teams_timetable_edits"
down_revision: str | Sequence[str] | None = "teams_timetable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("timetable_slot", sa.Column("last_on", sa.Date(), nullable=True), schema="teams")
    op.add_column(
        "lesson",
        sa.Column("single", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="teams",
    )


def downgrade() -> None:
    op.drop_column("lesson", "single", schema="teams")
    op.drop_column("timetable_slot", "last_on", schema="teams")
