"""teams hand-ins: what a Submission's hand-in is made of and where the drive delta continues

Revision ID: teams_handins
Revises: teams_assignments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "teams_handins"
down_revision: str | Sequence[str] | None = "teams_assignments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "submission",
        sa.Column("handed_in_at", sa.DateTime(timezone=True), nullable=True),
        schema="teams",
    )
    op.add_column(
        "submission",
        sa.Column("late", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="teams",
    )
    op.add_column("submission", sa.Column("signature", sa.Text(), nullable=True), schema="teams")
    op.add_column(
        "submission",
        sa.Column(
            "files",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        schema="teams",
    )
    op.add_column(
        "submission",
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        schema="teams",
    )
    op.add_column(
        "submission",
        sa.Column("pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="teams",
    )
    op.add_column(
        "submission",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="teams",
    )
    op.create_table(
        "handin_file",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["submission_id"], ["teams.submission.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="teams",
    )
    op.create_index(
        "ix_teams_handin_file_submission_id", "handin_file", ["submission_id"], schema="teams"
    )
    op.create_table(
        "handin_cursor",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("delta_link", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="teams",
    )


def downgrade() -> None:
    op.drop_table("handin_cursor", schema="teams")
    op.drop_table("handin_file", schema="teams")
    for column in ("locked", "pending", "changed_at", "files", "signature", "late", "handed_in_at"):
        op.drop_column("submission", column, schema="teams")
