import uuid
from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from classlop.shared.db import Base

Status = Literal["in_progress", "graded", "failed"]
Reading = Literal["readable", "unsure", "unreadable", "blank"]


class GradedSubmission(Base):
    """One grading result, keyed by the hand-in it was made for."""

    __tablename__ = "submission"
    __table_args__ = (
        CheckConstraint(f"status IN {get_args(Status)}", name="submission_status"),
        {"schema": "grading"},
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    handed_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    status: Mapped[str] = mapped_column(Text)
    held_reasons: Mapped[list] = mapped_column(JSONB)
    spot_check_reasons: Mapped[list] = mapped_column(JSONB)
    comment: Mapped[str] = mapped_column(Text)

    items: Mapped[list["GradedItem"]] = relationship(
        order_by="GradedItem.position", lazy="selectin", cascade="all, delete-orphan"
    )


class GradedItem(Base):
    __tablename__ = "item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["submission_id", "handed_in_at"],
            ["grading.submission.submission_id", "grading.submission.handed_in_at"],
            ondelete="CASCADE",
        ),
        CheckConstraint(f"reading IN {get_args(Reading)}", name="item_reading"),
        {"schema": "grading"},
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    handed_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    number: Mapped[int] = mapped_column(Integer)
    max_points: Mapped[int] = mapped_column(Integer)
    ai_points: Mapped[int] = mapped_column(Integer)
    reading: Mapped[str] = mapped_column(Text)
    drawing: Mapped[bool]
    ai_transcription: Mapped[str] = mapped_column(Text)
