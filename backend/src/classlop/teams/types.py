from datetime import date, datetime, time
from typing import Protocol

from pydantic import BaseModel


class NotOwner(Exception):
    """The Teacher does not own that team."""


class AlreadyLinked(Exception):
    """The team is already a Class."""


class TimetableExists(Exception):
    """The Class already has a Timetable."""


class Team(BaseModel):
    id: str
    name: str


class Class(BaseModel):
    id: str
    team_id: str
    general_channel_id: str
    name: str
    school_year_end: date | None = None


class Slot(BaseModel):
    """A weekly Timetable slot; weekday 0 is Monday, times are Warsaw wall-clock."""

    weekday: int
    start: time
    end: time


class Lesson(BaseModel):
    id: str
    class_id: str
    start: datetime
    end: datetime
    join_url: str
    topic: str | None = None
    cancelled: bool = False


class Student(BaseModel):
    id: str
    class_id: str
    user_id: str
    display_name: str
    upn: str
    former_since: datetime | None = None


class Teams(Protocol):
    """The `teams` area's interface: the real area and FakeTeams both implement it."""

    async def list_owned_teams(self) -> list[Team]: ...

    async def link_team(self, team_id: str) -> Class:
        """Raises NotOwner or AlreadyLinked; syncs the roster."""
        ...

    async def get_class(self, class_id: str) -> Class: ...

    async def list_classes(self) -> list[Class]: ...

    async def list_students(self, class_id: str) -> list[Student]:
        """Every Student, Former students included (`former_since` set)."""
        ...

    async def sync_roster(self, class_id: str) -> None: ...

    async def add_timetable(self, class_id: str, slots: list[Slot], school_year_end: date) -> None:
        """One recurring online-meeting event per slot, from the next such weekday to the
        school-year end, inviting the Students. Raises TimetableExists."""
        ...

    async def add_lesson(self, class_id: str, start: datetime, end: datetime, topic: str) -> Lesson:
        """One event with the Lesson topic in its title. Raises ValueError without a topic."""
        ...

    async def list_lessons(self, class_id: str) -> list[Lesson]:
        """Every Lesson of the Class by start: series occurrences and single Lessons."""
        ...

    async def cancel_lessons(self, class_id: str, first: date, last: date) -> None:
        """Cancel every Lesson on the dates first..last (Warsaw, inclusive). A cancelled Lesson
        stays listed with its Lesson topic."""
        ...

    async def change_slot(self, class_id: str, old: Slot, new: Slot, from_date: date) -> None:
        """End the series of `old` the day before `from_date` and start one of `new` on or after
        it, to the school-year end. Raises LookupError if `old` is not a current slot and
        ValueError if `from_date` is not after its first Lesson."""
        ...

    async def set_lesson_topic(self, class_id: str, lesson_id: str, topic: str) -> Lesson:
        """Set the Lesson topic and the occurrence title to "<Class>: <Lesson topic>". Raises
        ValueError for an empty topic and LookupError for a Lesson not in the Class."""
        ...
