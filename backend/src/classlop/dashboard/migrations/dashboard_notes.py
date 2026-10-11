"""dashboard notes: the Teacher's private remark about a Student

Revision ID: dashboard_notes
Revises: dashboard_base
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dashboard_notes"
down_revision: str | Sequence[str] | None = "dashboard_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "note",
        sa.Column("class_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("class_id", "student_id"),
        schema="dashboard",
    )


def downgrade() -> None:
    op.drop_table("note", schema="dashboard")
