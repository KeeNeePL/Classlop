"""dashboard records: Notes and the Suggested grade thresholds

Revision ID: dashboard_records
Revises: dashboard_base
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dashboard_records"
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
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("class_id", "student_id"),
        schema="dashboard",
    )
    op.create_table(
        "thresholds",
        sa.Column("id", sa.Boolean(), nullable=False),
        sa.Column("percents", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.CheckConstraint("id", name="thresholds_one_row"),
        sa.PrimaryKeyConstraint("id"),
        schema="dashboard",
    )


def downgrade() -> None:
    op.drop_table("thresholds", schema="dashboard")
    op.drop_table("note", schema="dashboard")
