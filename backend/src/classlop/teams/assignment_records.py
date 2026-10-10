"""Assignments and their Submissions. Imported by models.py so the migrations see them."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from classlop.shared.db import Base
from classlop.teams.types import AssignmentState, AssignmentType, SubmissionState


class AssignmentRecord(Base):
    __tablename__ = "assignment"
    __table_args__ = {"schema": "teams"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    class_id: Mapped[str] = mapped_column(
        ForeignKey("teams.class.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    type: Mapped[AssignmentType] = mapped_column(Text)
    state: Mapped[AssignmentState] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reminder_on: Mapped[bool] = mapped_column(Boolean)
    # Whole-Class Assignments go to Students who join later.
    whole_class: Mapped[bool] = mapped_column(Boolean)
    item_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    item_versions: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list)
    given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    give_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The Items PDF in storage, kept until the Assignment is Given.
    pdf_key: Mapped[str | None] = mapped_column(Text)
    post_id: Mapped[str | None] = mapped_column(Text)
    post_channel_id: Mapped[str | None] = mapped_column(Text)
    # `Classlop/<Class>/<Assignment>` in the Teacher's OneDrive, holding every Student's folder.
    folder_id: Mapped[str | None] = mapped_column(Text)


class SubmissionRecord(Base):
    __tablename__ = "submission"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id"), {"schema": "teams"})

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("teams.assignment.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("teams.student.id", ondelete="CASCADE"))
    state: Mapped[SubmissionState] = mapped_column(Text, default="not_handed_in")
    folder_id: Mapped[str | None] = mapped_column(Text)
    folder_url: Mapped[str | None] = mapped_column(Text)
    permission_id: Mapped[str | None] = mapped_column(Text)
    chat_id: Mapped[str | None] = mapped_column(Text)
    notice_id: Mapped[str | None] = mapped_column(Text)
    # The hand-in, settled after 3 quiet minutes: its time, whether it is a Late submission, the
    # signature of its file set and its copies in storage.
    handed_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    signature: Mapped[str | None] = mapped_column(Text)
    files: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # The last change seen in the folder, and whether it has yet to settle.
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    # The folder's sharing permission is read-only.
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    # Why the Teacher excused it, for the Teacher only.
    excused_reason: Mapped[str | None] = mapped_column(Text)
