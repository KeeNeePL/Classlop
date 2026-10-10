import uuid
from datetime import datetime
from typing import get_args

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from classlop.items.types import Difficulty, ItemFormat, Origin
from classlop.shared.db import Base


class ItemRow(Base):
    __tablename__ = "item"
    __table_args__ = (
        CheckConstraint(f"origin IN {get_args(Origin)}", name="item_origin"),
        {"schema": "items"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    origin: Mapped[str] = mapped_column(Text)
    # The Chat for "chat" and "upload", the Class for "nowa_praca".
    origin_ref: Mapped[str | None] = mapped_column(Text)
    source_file: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)
    exemplar_ids: Mapped[list] = mapped_column(JSONB, default=list)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(Text)
    retired: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VersionRow(Base):
    """Insert-only: a trigger rejects updates and deletes."""

    __tablename__ = "version"
    __table_args__ = (
        UniqueConstraint("item_id", "number"),
        CheckConstraint(f"item_format IN {get_args(ItemFormat)}", name="version_item_format"),
        CheckConstraint(f"difficulty IN {get_args(Difficulty)}", name="version_difficulty"),
        {"schema": "items"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.item.id"))
    number: Mapped[int] = mapped_column(Integer)
    item_format: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    points: Mapped[int] = mapped_column(Integer)
    difficulty: Mapped[str] = mapped_column(Text)
    curriculum_topics: Mapped[list] = mapped_column(JSONB)
    general_requirements: Mapped[list] = mapped_column(JSONB)
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    correct_options: Mapped[list] = mapped_column(JSONB, default=list)
    answer: Mapped[str | None] = mapped_column(Text)
    rubric: Mapped[list] = mapped_column(JSONB, default=list)
    model_solution: Mapped[str | None] = mapped_column(Text)
    # The tag fields the Teacher set by hand; a re-tag keeps them.
    teacher_tags: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageRow(Base):
    __tablename__ = "usage"
    __table_args__ = (UniqueConstraint("assignment_id", "item_id"), {"schema": "items"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.item.id"))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.version.id"))
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
