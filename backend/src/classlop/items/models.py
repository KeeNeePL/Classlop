import uuid
from datetime import datetime
from typing import get_args

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from classlop.items.types import Flag, Origin
from classlop.shared.db import Base


class ItemRecord(Base):
    __tablename__ = "item"
    __table_args__ = (
        CheckConstraint(f"origin IN {get_args(Origin)}", name="item_origin"),
        CheckConstraint(f"flag IN {get_args(Flag)}", name="item_flag"),
        {"schema": "items"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    origin: Mapped[str] = mapped_column(Text)
    source_key: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)
    exemplar_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    flag: Mapped[str | None] = mapped_column(Text)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VersionRecord(Base):
    """Written once, never updated: the latest number is the Item's current version."""

    __tablename__ = "item_version"
    __table_args__ = (UniqueConstraint("item_id", "number"), {"schema": "items"})

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.item.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    item_format: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    points: Mapped[int] = mapped_column(Integer)
    options: Mapped[dict] = mapped_column(JSONB)
    correct_options: Mapped[list[str]] = mapped_column(ARRAY(Text))
    answer: Mapped[str | None] = mapped_column(Text)
    model_solution: Mapped[str | None] = mapped_column(Text)
    rubric: Mapped[list] = mapped_column(JSONB)
    difficulty: Mapped[str] = mapped_column(Text)
    curriculum_topics: Mapped[list] = mapped_column(JSONB)
    general_requirements: Mapped[list[str]] = mapped_column(ARRAY(Text))
    tag_probabilities: Mapped[dict] = mapped_column(JSONB)
    # Tags the Teacher set ("difficulty", ...); later versions keep them through a re-tag.
    teacher_tags: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageRecord(Base):
    """An Item given in an Assignment, pinned to the version the Class got."""

    __tablename__ = "usage"
    __table_args__ = {"schema": "items"}

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.item.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.item_version.id"))
    class_id: Mapped[str] = mapped_column(Text)
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
