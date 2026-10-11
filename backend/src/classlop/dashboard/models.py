from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from classlop.shared.db import Base


class NoteRow(Base):
    """The Teacher's private Note on one Student of one Class; never in any export."""

    __tablename__ = "note"
    __table_args__ = {"schema": "dashboard"}

    class_id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_id: Mapped[str] = mapped_column(Text, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ThresholdsRow(Base):
    """The one set of Suggested grade thresholds: the lowest percent for grades 2 to 6."""

    __tablename__ = "thresholds"
    __table_args__ = (CheckConstraint("id", name="thresholds_one_row"), {"schema": "dashboard"})

    id: Mapped[bool] = mapped_column(Boolean, primary_key=True, default=True)
    percents: Mapped[list[int]] = mapped_column(ARRAY(Integer))
