"""items records: Items, their immutable versions and usage

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

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "item",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("origin_ref", sa.Text(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("exemplar_ids", JSONB, nullable=False),
        sa.Column("flagged", sa.Boolean(), nullable=False),
        sa.Column("flag_reason", sa.Text(), nullable=True),
        sa.Column("retired", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("origin IN ('chat', 'upload', 'nowa_praca')", name="item_origin"),
        sa.PrimaryKeyConstraint("id"),
        schema="items",
    )
    op.create_table(
        "version",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("item_format", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.Text(), nullable=False),
        sa.Column("curriculum_topics", JSONB, nullable=False),
        sa.Column("general_requirements", JSONB, nullable=False),
        sa.Column("options", JSONB, nullable=False),
        sa.Column("correct_options", JSONB, nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("rubric", JSONB, nullable=False),
        sa.Column("model_solution", sa.Text(), nullable=True),
        sa.Column("teacher_tags", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("item_format IN ('closed', 'open')", name="version_item_format"),
        sa.CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="version_difficulty"),
        sa.ForeignKeyConstraint(["item_id"], ["items.item.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "number"),
        schema="items",
    )
    op.create_table(
        "usage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("given_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.item.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["items.version.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "item_id"),
        schema="items",
    )
    op.create_index("ix_items_usage_class_id", "usage", ["class_id"], schema="items")
    op.execute(
        """
        CREATE FUNCTION items.version_is_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'item versions are immutable';
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER version_is_immutable BEFORE UPDATE OR DELETE ON items.version
        FOR EACH ROW EXECUTE FUNCTION items.version_is_immutable()
        """
    )


def downgrade() -> None:
    op.drop_table("usage", schema="items")
    op.drop_table("version", schema="items")
    op.drop_table("item", schema="items")
    op.execute("DROP FUNCTION items.version_is_immutable()")
