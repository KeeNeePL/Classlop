from datetime import date, datetime, time, timedelta
from typing import Literal, Protocol

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
    cancelled: bool = False


class Student(BaseModel):
    id: str
    class_id: str
    user_id: str
    display_name: str
    upn: str
    former_since: datetime | None = None


AttendanceState = Literal["present", "late", "absent"]


class Attendee(BaseModel):
    """Someone Teams reported at a Lesson. `key` is their account, or for a guest their name."""

    key: str
    user_id: str | None
    display_name: str
    first_join: datetime
    seconds: int


class AttendanceEntry(BaseModel):
    student_id: str
    state: AttendanceState | None
    minutes: int
    overridden: bool


class UnmatchedAttendee(BaseModel):
    key: str
    display_name: str
    minutes: int


class Attendance(BaseModel):
    """`fetched_at` is None until the first fetch, when every `state` is unknown (None)."""

    lesson_id: str
    fetched_at: datetime | None
    entries: list[AttendanceEntry]
    unmatched: list[UnmatchedAttendee]


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

    async def get_attendance(self, class_id: str, lesson_id: str) -> Attendance:
        """What is known now: Students' states, overrides applied, and Unmatched attendees."""
        ...

    async def refresh_attendance(self, class_id: str, lesson_id: str) -> Attendance:
        """Fetch the Lesson's Attendance from Teams now, merging every record in its window."""
        ...

    async def fetch_due_attendance(self) -> int:
        """Fetch for each Lesson ended 45 minutes ago and again at 2 hours; returns how many."""
        ...

    async def override_attendance(
        self, class_id: str, lesson_id: str, student_id: str, state: AttendanceState | None
    ) -> None:
        """Set the Teacher's state, kept through every fetch; None removes the override."""
        ...

    async def link_attendee(self, class_id: str, key: str, student_id: str) -> None:
        """Remember an Unmatched attendee as a Student, for this and later Lessons."""
        ...

    async def lateness_threshold(self) -> timedelta: ...

    async def set_lateness_threshold(self, threshold: timedelta) -> None: ...

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
