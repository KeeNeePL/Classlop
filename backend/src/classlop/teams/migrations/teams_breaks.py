"""teams breaks: the date ranges a Class has cancelled, kept for slot changes

Revision ID: teams_breaks
Revises: teams_excused
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "teams_breaks"
down_revision: str | Sequence[str] | None = "teams_excused"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "break",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "class_id",
            sa.Text(),
            sa.ForeignKey("teams.class.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("first", sa.Date(), nullable=False),
        sa.Column("last", sa.Date(), nullable=False),
        schema="teams",
    )


def downgrade() -> None:
    op.drop_table("break", schema="teams")
