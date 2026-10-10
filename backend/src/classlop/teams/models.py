from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
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
    # The series' last day once the slot has been replaced.
    last_on: Mapped[date | None] = mapped_column(Date)


class LessonRecord(Base):
    """A Lesson's topic. Occurrences are read from the calendar; a record exists once one has a
    topic. `single` marks Lessons added by hand."""

    __tablename__ = "lesson"
    __table_args__ = {"schema": "teams"}

    # The calendar event id.
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    class_id: Mapped[str] = mapped_column(
        ForeignKey("teams.class.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[str] = mapped_column(Text)
    single: Mapped[bool] = mapped_column(Boolean, default=True)


class CalendarSeriesRecord(Base):
    """An online meeting of the Teacher's calendar, a recurring series or a single event, and where
    it belongs: a Class's lesson, a pending question, kept as a calendar event, or hidden."""

    __tablename__ = "calendar_series"
    __table_args__ = {"schema": "teams"}

    # The series master's id, or the event's own.
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)  # lesson, pending, kept or hidden
    class_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.class.id", ondelete="CASCADE"), index=True
    )
    # Classes a pending question offers; none means keep or hide.
    candidates: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


class CalendarEventRecord(Base):
    """One occurrence as the calendar delta last reported it."""

    __tablename__ = "calendar_event"
    __table_args__ = {"schema": "teams"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    series_id: Mapped[str] = mapped_column(
        ForeignKey("teams.calendar_series.id", ondelete="CASCADE"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    join_url: Mapped[str] = mapped_column(Text)


class CalendarCursor(Base):
    """Where the calendar delta continues, valid for the day it was taken."""

    __tablename__ = "calendar_cursor"
    __table_args__ = {"schema": "teams"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    delta_link: Mapped[str] = mapped_column(Text)
    day: Mapped[date] = mapped_column(Date)
