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


class Candidate(BaseModel):
    """A tenant user the Teacher may pick as a Student."""

    user_id: str
    display_name: str
    upn: str


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

    async def sync_roster(self, class_id: str) -> None:
        """Also renames the Class to match its team."""
        ...

    async def search_users(self, query: str) -> list[Candidate]:
        """Tenant users whose name has a word starting with `query`."""
        ...

    async def create_class(self, name: str, student_user_ids: list[str]) -> Class:
        """A new Private team named `name`, the Teacher as owner and the users as members."""
        ...

    async def add_student(self, class_id: str, user_id: str) -> Student: ...

    async def remove_student(self, class_id: str, user_id: str) -> None:
        """Removes them from the team; they become a Former student."""
        ...

    async def rename_class(self, class_id: str, name: str) -> Class:
        """Renames the team too."""
        ...

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
