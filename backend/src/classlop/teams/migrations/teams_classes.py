"""teams classes and students

Revision ID: teams_classes
Revises: teams_base
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "teams_classes"
down_revision: str | Sequence[str] | None = "teams_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "class",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("team_id", sa.Text(), nullable=False),
        sa.Column("general_channel_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id"),
        schema="teams",
    )
    op.create_table(
        "student",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("class_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("upn", sa.Text(), nullable=False),
        sa.Column("former_since", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["class_id"], ["teams.class.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("class_id", "user_id"),
        schema="teams",
    )
    op.create_index("ix_teams_student_class_id", "student", ["class_id"], schema="teams")


def downgrade() -> None:
    op.drop_table("student", schema="teams")
    op.drop_table("class", schema="teams")
