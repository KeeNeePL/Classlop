import uuid
from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, Text, func
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
    # The Assignment's due time; before it the Teacher cannot override an on-time Submission.
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by Zatwierdź: the Submission is neither Held nor flagged any more.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    held_reasons: Mapped[list] = mapped_column(JSONB)
    spot_check_reasons: Mapped[list] = mapped_column(JSONB)
    # Regenerated only when the Feedback text changes, never for an Override.
    summary: Mapped[str] = mapped_column(Text, server_default="")
    comment: Mapped[str] = mapped_column(Text)
    # The current Feedback PDF; none when there is nothing to typeset or it would not typeset.
    pdf_key: Mapped[str | None] = mapped_column(Text)
    # The `grading.grade` payload, run again by Oceń ponownie.
    grade_job: Mapped[dict | None] = mapped_column(JSONB)

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
    # The Teacher's fix of a misread Transcription; the Item's AI fields were graded from it.
    fixed_transcription: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str] = mapped_column(Text)
    # The Teacher's wording, shown instead of the AI's Feedback.
    edited_feedback: Mapped[str | None] = mapped_column(Text)
    # A short name for the mistake, gathered into Common mistakes.
    mistake: Mapped[str | None] = mapped_column(Text)
    # What the verification read disputed in the Transcription, or that it skipped the Item.
    verification_note: Mapped[str | None] = mapped_column(Text)
    # The Item's Curriculum topic names, kept so "Do powtórki" is rebuilt without `items`.
    curriculum_topics: Mapped[list] = mapped_column(JSONB, server_default="[]")

    override_record: Mapped["Override | None"] = relationship(lazy="selectin", viewonly=True)

    @property
    def override(self) -> int | None:
        return self.override_record.points if self.override_record else None

    @property
    def effective_points(self) -> int:
        return self.ai_points if self.override is None else self.override


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


class Override(Base):
    """The Teacher's points for one Item, kept beside the AI's and never read by grading."""

    __tablename__ = "override"
    __table_args__ = (
        ForeignKeyConstraint(
            ["submission_id", "handed_in_at", "item_id"],
            ["grading.item.submission_id", "grading.item.handed_in_at", "grading.item.item_id"],
            ondelete="CASCADE",
        ),
        {"schema": "grading"},
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    handed_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    points: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
