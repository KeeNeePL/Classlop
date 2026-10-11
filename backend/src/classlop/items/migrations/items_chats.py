"""items chats: named Chats

Revision ID: items_chats
Revises: items_upload
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "items_chats"
down_revision: str | Sequence[str] | None = "items_upload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="items",
    )


def downgrade() -> None:
    op.drop_table("chat", schema="items")
