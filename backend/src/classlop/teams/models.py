from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from classlop.shared.db import Base


class ClassRecord(Base):
    __tablename__ = "class"
    __table_args__ = {"schema": "teams"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    team_id: Mapped[str] = mapped_column(Text, unique=True)
    general_channel_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)


class StudentRecord(Base):
    __tablename__ = "student"
    __table_args__ = (UniqueConstraint("class_id", "user_id"), {"schema": "teams"})

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    class_id: Mapped[str] = mapped_column(
        ForeignKey("teams.class.id", ondelete="CASCADE"), index=True
    )
    # The Entra user id.
    user_id: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    upn: Mapped[str] = mapped_column(Text)
    former_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
