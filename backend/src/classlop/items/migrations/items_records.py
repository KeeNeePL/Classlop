"""items records: Items, their versions and usage

Revision ID: items_records
Revises: items_base
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "items_records"
down_revision: str | Sequence[str] | None = "items_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "item",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("exemplar_ids", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("flag", sa.Text(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "flag IN ('no_exemplar', 'failed_tag_check', 'unsure_extraction')", name="item_flag"
        ),
        sa.CheckConstraint("origin IN ('generated', 'uploaded')", name="item_origin"),
        sa.PrimaryKeyConstraint("id"),
        schema="items",
    )
    op.create_table(
        "item_version",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("item_format", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correct_options", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("model_solution", sa.Text(), nullable=True),
        sa.Column("rubric", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("difficulty", sa.Text(), nullable=False),
        sa.Column("curriculum_topics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("general_requirements", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("tag_probabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("teacher_tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "number"),
        schema="items",
    )
    op.create_table(
        "usage",
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("class_id", sa.Text(), nullable=False),
        sa.Column("given_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["items.item_version.id"],
        ),
        sa.PrimaryKeyConstraint("assignment_id", "item_id"),
        schema="items",
    )
    op.create_index(
        op.f("ix_items_usage_item_id"), "usage", ["item_id"], unique=False, schema="items"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_items_usage_item_id"), table_name="usage", schema="items")
    op.drop_table("usage", schema="items")
    op.drop_table("item_version", schema="items")
    op.drop_table("item", schema="items")
