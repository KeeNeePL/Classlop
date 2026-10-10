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
    # Nullable only for results graded before Common mistakes existed.
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
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
    doubt: Mapped[bool]
    ai_transcription: Mapped[str] = mapped_column(Text)
    feedback: Mapped[str] = mapped_column(Text)
    # A short name for the mistake, gathered into Common mistakes.
    mistake: Mapped[str | None] = mapped_column(Text)
    # What the verification read disputed in the Transcription, or that it skipped the Item.
    verification_note: Mapped[str | None] = mapped_column(Text)


class CommonMistake(Base):
    """One Common mistake on one Item of one Assignment, kept per Item so a later view across
    Assignments is only a query."""

    __tablename__ = "common_mistake"
    __table_args__ = {"schema": "grading"}

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    submission_ids: Mapped[list] = mapped_column(JSONB)


class CommonMistakesRun(Base):
    """Per Assignment: the latest recompute request, which older delayed jobs see and stand
    down for, and the last recompute, after which every newly graded Submission asks again."""

    __tablename__ = "common_mistakes_run"
    __table_args__ = {"schema": "grading"}

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
