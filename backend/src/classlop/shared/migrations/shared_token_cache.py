"""the MSAL token cache

Revision ID: shared_token_cache
Revises: shared_jobs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "shared_token_cache"
down_revision: str | Sequence[str] | None = "shared_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "token_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_table("token_cache", schema="shared")
