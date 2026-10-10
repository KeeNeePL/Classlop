"""What returning Feedback has done for a Submission. Imported by models.py so the migrations see
it."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from classlop.shared.db import Base


class FeedbackRecord(Base):
    """One message of Feedback to a Student, for one version of the Feedback PDF (`pdf_key`, empty
    when there is none). It records each step as it is done, so a repeat resumes where one
    stopped; `message_id` is set once the message is sent."""

    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("submission_id", "pdf_key"), {"schema": "teams"})

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("teams.submission.id", ondelete="CASCADE"), index=True
    )
    pdf_key: Mapped[str] = mapped_column(Text)
    # The PDF in the Teacher's OneDrive: its item, the id a message refers to it by and its link.
    item_id: Mapped[str | None] = mapped_column(Text)
    attachment_id: Mapped[str | None] = mapped_column(Text)
    web_url: Mapped[str | None] = mapped_column(Text)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    message_id: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
