import uuid
from datetime import date, datetime, time, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel


class NotOwner(Exception):
    pass


class AlreadyLinked(Exception):
    pass


class TimetableExists(Exception):
    pass


SeriesState = Literal["lesson", "pending", "kept", "hidden"]
LESSON: SeriesState = "lesson"
PENDING: SeriesState = "pending"
KEPT: SeriesState = "kept"
HIDDEN: SeriesState = "hidden"
# A pending question without a Class is answered keep or hide; each leaves one state.
VERDICTS: dict[str, SeriesState] = {"keep": KEPT, "hide": HIDDEN}


class Team(BaseModel):
    id: str
    name: str


class Candidate(BaseModel):
    user_id: str
    display_name: str
    upn: str


class ClassReadOnly(Exception):
    """The Class's team was deleted in Teams: nothing changes until it is restored or deleted."""


# "team_deleted" is read-only: the team is gone from Teams, `team_deleted_at` is when it was found.
ClassState = Literal["active", "team_deleted"]


class Class(BaseModel):
    id: str
    team_id: str
    general_channel_id: str
    name: str
    school_year_end: date | None = None
    state: ClassState = "active"
    team_deleted_at: datetime | None = None


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


class CalendarQuestion(BaseModel):
    """A Teams meeting the Teacher is asked about, once per series: which of `candidates` (Class
    ids) it belongs to, or, with none, whether to keep it as a calendar event or hide it."""

    id: str
    subject: str
    start: datetime
    candidates: list[str]


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


AssignmentType = Literal["homework", "quiz", "exam"]
# Scheduled and Open are Given. Draft is not Given, and is where a Scheduled one returns when its
# post fails (`give_failed_at`). Closed is set when #57 closes it.
AssignmentState = Literal["draft", "scheduled", "open", "closed"]
SubmissionState = Literal["not_handed_in", "handed_in", "graded", "returned", "missing", "excused"]


class AssignmentSpec(BaseModel):
    """What the caller decides about an Assignment. `student_ids` None means the whole Class."""

    title: str
    type: AssignmentType
    due_at: datetime
    close_at: datetime
    item_ids: list[uuid.UUID]
    student_ids: list[str] | None = None
    reminder_on: bool = True


class Assignment(BaseModel):
    """`item_versions` are the frozen Item versions in the order of `item_ids`, known once the
    Assignment is Given. `given_at` is when it was Given, `publish_at` when a Scheduled one is
    posted. Ids are ULIDs; see ids.py for the UUIDs `items` and `grading` use."""

    id: str
    class_id: str
    title: str
    type: AssignmentType
    state: AssignmentState
    due_at: datetime
    close_at: datetime
    reminder_on: bool
    whole_class: bool
    item_ids: list[uuid.UUID]
    item_versions: list[uuid.UUID] = []
    given_at: datetime | None = None
    publish_at: datetime | None = None
    give_failed_at: datetime | None = None
    post_id: str | None = None
    post_channel_id: str | None = None


class Submission(BaseModel):
    """One Student's work on an Assignment. The folder is the Student's private hand-in folder in
    the Teacher's OneDrive, `permission_id` their sharing permission on it, `chat_id` their 1:1
    chat with the Teacher and `notice_id` the «Nowa praca» message in it (None until sent).

    `handed_in_at` is the server time of the hand-in's last upload, `late` marks a Late
    submission (handed in after the due time) and `files` are the hand-in's copies in storage.
    A hand-in settles after 3 quiet minutes; until then the folder's files are not yet the
    Submission's. `excused_reason` is the Teacher's private note on an Excused Submission."""

    id: str
    assignment_id: str
    student_id: str
    state: SubmissionState = "not_handed_in"
    folder_id: str | None = None
    folder_url: str | None = None
    permission_id: str | None = None
    chat_id: str | None = None
    notice_id: str | None = None
    handed_in_at: datetime | None = None
    late: bool = False
    files: list[str] = []
    excused_reason: str | None = None


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
        """Every Lesson of the Class by start: series occurrences, single Lessons and Teams
        meetings attached to it. Lessons cancelled in Teams stay, marked `cancelled`."""
        ...

    async def sync_calendar(self) -> None:
        """Pull what changed in the Teacher's calendar, 7 days back to 60 ahead. Teams wins on
        time and cancellation; a new Teams meeting is attached to a Class by its channel or by
        invitees that are exactly the Class's Students, else it becomes a CalendarQuestion."""
        ...

    async def list_calendar_questions(self) -> list[CalendarQuestion]: ...

    async def answer_calendar_question(self, question_id: str, answer: str) -> None:
        """`answer` is one of the question's candidate Class ids, or "keep" or "hide"; it covers
        every occurrence of the series. Raises ValueError for anything else."""
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

    async def give_assignment(
        self, class_id: str, spec: AssignmentSpec, items_pdf: bytes, when: datetime | None = None
    ) -> Assignment:
        """Give the Assignment now (Open) or at `when` (Scheduled), after syncing the roster.
        Posting it in General with the Items PDF and the due time makes it Given: its Items are
        frozen by `items.give()`, a Scheduled one's at once. Each recipient then gets a private
        hand-in folder and a «Nowa praca» chat message. Raises ValueError for a title without
        letters, a close before the due time, `when` in the past, or a Student of another Class."""
        ...

    async def get_assignment(self, assignment_id: str) -> Assignment: ...

    async def list_assignments(self, class_id: str) -> list[Assignment]:
        """Every Assignment of the Class, by due time."""
        ...

    async def give_again(self, assignment_id: str, when: datetime | None = None) -> Assignment:
        """Give a Draft now or at `when`, as `give_assignment` does; its Items stay as frozen.
        Raises ValueError unless the Assignment is a Draft."""
        ...

    async def publish_scheduled(self, assignment_id: str, last_try: bool = False) -> Assignment:
        """What the schedule runs at the given time: post a Scheduled Assignment and deliver it.
        On `last_try`, a post that still fails returns it to Draft with `give_failed_at` set
        (nothing happens if Teams already accepted the post); before that the error is raised so
        the job is tried again. Does nothing for an Assignment that is not Scheduled."""
        ...

    async def list_failed_gives(self) -> list[Assignment]:
        """Drafts that failed to be given: the home screen's «nie udało się wydać»."""
        ...

    async def deliver_assignment(self, assignment_id: str) -> int:
        """Give each recipient still without them their folder, sharing and «Nowa praca» message,
        one Student at a time so that a failure for one leaves the others done. Returns how many
        are still waiting. Giving queues a job that calls this until none are."""
        ...

    async def list_submissions(self, assignment_id: str) -> list[Submission]:
        """One per recipient, in the order they were created."""
        ...

    async def delete_class(self, class_id: str, name: str) -> None:
        """Delete the Class from Classlop and Teams once `name` is typed as the Class's name:
        its team (Microsoft keeps it restorable for 30 days), the future Lesson events, the
        hand-in folders, the schedules of its Assignments and its records. Items and the Students'
        1:1 chats stay; `dashboard` deletes its own Notes. Raises ValueError for another name.
        Also works on a Class whose team was deleted in Teams."""
        ...

    async def list_deleted_teams(self) -> list[Class]:
        """Classes whose team was deleted in Teams, read-only until the Teacher restores the team
        (`restore_team`, or in Teams) or deletes the Class: the home screen's «przywróć zespół»
        and «usuń klasę». A Class still in this state 30 days after `team_deleted_at` is deleted
        by the next roster sync."""
        ...

    async def restore_team(self, class_id: str) -> Class:
        """Ask Teams to restore the Class's deleted team, then sync: the Class is active again.
        A team restored in Teams does the same on the next roster sync."""
        ...

    async def poll_handins(self) -> int:
        """Read what Students uploaded into their folders: a set unchanged for 3 minutes becomes
        the Submission's hand-in (Handed in, Late if after the due time, graded on its own), a
        change before return replaces it, no files at all is Not handed in. Also closes what is
        due to close. Returns how many Submissions changed state."""
        ...

    async def close_due_assignments(self) -> int:
        """Close each Open Assignment whose close time has come: what is settled stays, Students
        who have not handed in are Missing, and every folder's sharing permission becomes read.
        Files uploaded after the close time are ignored. Returns how many Submissions went
        Missing or were settled by the close."""
        ...

    async def change_times(
        self, assignment_id: str, due_at: datetime | None = None, close_at: datetime | None = None
    ) -> Assignment:
        """Move the due and/or close time of a Scheduled or Open Assignment (None keeps one). A
        new due time corrects the post in General and replies "Zmiana terminu: ..." in its thread,
        so Students are notified; a Scheduled Assignment has no post yet and posts the new time.
        The Reminder and the due-time return follow the due time. Raises ValueError for any other
        state or a close before the due time."""
        ...

    async def add_recipients(self, assignment_id: str, student_ids: list[str]) -> list[Submission]:
        """Give the Students (current Students of the Class) a Scheduled or Open Assignment too:
        each gets a folder and a «Nowa praca» message, a Scheduled one's when it is posted.
        Students who have it already are skipped; returns the new Submissions. A whole-Class
        Assignment also reaches every Student who joins the Class, at the roster sync. Raises
        ValueError for another Class's Student, a Former student or an Assignment not Given or
        already Closed."""
        ...

    async def excuse_submission(self, submission_id: str, reason: str | None = None) -> Submission:
        """Mark the Submission Excused, at any time and whatever its state: it drops out of all
        results and takes no more files. The optional `reason` is the Teacher's private note and
        is never sent to the Student."""
        ...
