"""items upload: pending near-duplicates and Chat messages

Revision ID: items_upload
Revises: items_exemplars
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "items_upload"
down_revision: str | Sequence[str] | None = "items_exemplars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "pending_duplicate",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("upload_id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("crop", sa.Text(), nullable=False),
        sa.Column("flag_reason", sa.Text(), nullable=True),
        sa.Column("nearest_item_id", sa.UUID(), nullable=False),
        sa.Column("cosine", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="items",
    )
    op.create_index(
        "ix_pending_duplicate_upload_id",
        "pending_duplicate",
        ["upload_id"],
        schema="items",
    )
    op.create_table(
        "chat_message",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="items",
    )
    op.create_index("ix_chat_message_chat_id", "chat_message", ["chat_id"], schema="items")


def downgrade() -> None:
    op.drop_table("chat_message", schema="items")
    op.drop_table("pending_duplicate", schema="items")
