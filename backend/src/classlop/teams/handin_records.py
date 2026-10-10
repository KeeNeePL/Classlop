"""What the hand-in polling remembers. Imported by models.py so the migrations see it."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from classlop.shared.db import Base


class HandinFileRecord(Base):
    """A file in a Student's hand-in folder, by its OneDrive item id. `s3_key` is its copy."""

    __tablename__ = "handin_file"
    __table_args__ = {"schema": "teams"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("teams.submission.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    s3_key: Mapped[str | None] = mapped_column(Text)


class HandinCursor(Base):
    """Where the Teacher's drive delta continues."""

    __tablename__ = "handin_cursor"
    __table_args__ = {"schema": "teams"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    delta_link: Mapped[str] = mapped_column(Text)
