from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from classlop.shared.db import Base


class ClassRecord(Base):
    __tablename__ = "class"
    __table_args__ = {"schema": "teams"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    team_id: Mapped[str] = mapped_column(Text, unique=True)
    general_channel_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    school_year_end: Mapped[date | None] = mapped_column(Date)


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


class SlotRecord(Base):
    """A Timetable slot: the series event in the Teacher's calendar."""

    __tablename__ = "timetable_slot"
    __table_args__ = {"schema": "teams"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    class_id: Mapped[str] = mapped_column(
        ForeignKey("teams.class.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[str] = mapped_column(Text)
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    first_on: Mapped[date] = mapped_column(Date)


class LessonRecord(Base):
    """A single Lesson added by hand; series occurrences are read from the calendar."""

    __tablename__ = "lesson"
    __table_args__ = {"schema": "teams"}

    # The calendar event id.
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    class_id: Mapped[str] = mapped_column(
        ForeignKey("teams.class.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[str] = mapped_column(Text)


def _class_fk():
    return mapped_column(ForeignKey("teams.class.id", ondelete="CASCADE"), index=True)


class FetchRecord(Base):
    """A Lesson whose Attendance has been fetched; `start` is what Late is measured from."""

    __tablename__ = "attendance_fetch"
    __table_args__ = {"schema": "teams"}

    lesson_id: Mapped[str] = mapped_column(Text, primary_key=True)
    class_id: Mapped[str] = _class_fk()
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AttendeeRecord(Base):
    """One person in a Lesson's Teams attendance, as of the last fetch."""

    __tablename__ = "attendee"
    __table_args__ = {"schema": "teams"}

    lesson_id: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    class_id: Mapped[str] = _class_fk()
    user_id: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    first_join: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seconds: Mapped[int] = mapped_column(Integer)


class OverrideRecord(Base):
    __tablename__ = "attendance_override"
    __table_args__ = {"schema": "teams"}

    lesson_id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("teams.student.id", ondelete="CASCADE"), primary_key=True
    )
    class_id: Mapped[str] = _class_fk()
    state: Mapped[str] = mapped_column(Text)


class LinkRecord(Base):
    __tablename__ = "attendee_link"
    __table_args__ = {"schema": "teams"}

    class_id: Mapped[str] = mapped_column(
        ForeignKey("teams.class.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("teams.student.id", ondelete="CASCADE"))


class SettingRecord(Base):
    __tablename__ = "setting"
    __table_args__ = {"schema": "teams"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
