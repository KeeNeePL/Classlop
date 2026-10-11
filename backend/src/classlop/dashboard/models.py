from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from classlop.shared.db import Base


class NoteRecord(Base):
    """The Teacher's private remark about a Student, one per Student of a Class."""

    __tablename__ = "note"
    __table_args__ = {"schema": "dashboard"}

    class_id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_id: Mapped[str] = mapped_column(Text, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
