"""teams class state: a Class whose team was deleted in Teams

Revision ID: teams_class_state
Revises: teams_assignments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "teams_class_state"
down_revision: str | Sequence[str] | None = "teams_assignments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "class",
        sa.Column("state", sa.Text(), nullable=False, server_default="active"),
        schema="teams",
    )
    op.add_column(
        "class",
        sa.Column("team_deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="teams",
    )


def downgrade() -> None:
    op.drop_column("class", "team_deleted_at", schema="teams")
    op.drop_column("class", "state", schema="teams")
