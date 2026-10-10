"""The `teams` area: Classlop's only link to Teams. Other areas call the functions below; they
are served by the real area over Graph, or by FakeTeams when TEAMS_BACKEND=fake. `dashboard`
passes GRAPH_SCOPES to sign-in, so the Teacher consents to what `teams` uses."""

from datetime import date, datetime, timedelta

from classlop.shared.auth import app_token
from classlop.shared.settings import get_settings
from classlop.teams.graph import GRAPH_SCOPES, GraphClient
from classlop.teams.types import (
    AlreadyLinked,
    Assignment,
    AssignmentSpec,
    Attendance,
    AttendanceEntry,
    AttendanceState,
    CalendarQuestion,
    Candidate,
    Class,
    Lesson,
    NotOwner,
    Slot,
    Student,
    Submission,
    Team,
    Teams,
    TimetableExists,
    UnmatchedAttendee,
)

__all__ = [
    "GRAPH_SCOPES",
    "AlreadyLinked",
    "Assignment",
    "AssignmentSpec",
    "CalendarQuestion",
    "Attendance",
    "AttendanceEntry",
    "AttendanceState",
    "Candidate",
    "Class",
    "Lesson",
    "NotOwner",
    "Slot",
    "Student",
    "Submission",
    "Team",
    "Teams",
    "TimetableExists",
    "UnmatchedAttendee",
    "add_lesson",
    "add_student",
    "add_timetable",
    "answer_calendar_question",
    "backend",
    "cancel_lessons",
    "change_slot",
    "close_due_assignments",
    "create_class",
    "deliver_assignment",
    "fetch_due_attendance",
    "get_attendance",
    "get_assignment",
    "give_again",
    "list_failed_gives",
    "publish_scheduled",
    "list_assignments",
    "list_submissions",
    "get_class",
    "give_assignment",
    "lateness_threshold",
    "link_attendee",
    "link_team",
    "list_calendar_questions",
    "override_attendance",
    "poll_handins",
    "refresh_attendance",
    "set_lateness_threshold",
    "list_lessons",
    "list_classes",
    "list_owned_teams",
    "list_students",
    "sync_calendar",
    "remove_student",
    "rename_class",
    "search_users",
    "set_lesson_topic",
    "sync_roster",
]

_backend: Teams | None = None


def backend() -> Teams:
    global _backend
    if _backend is None:
        if get_settings().teams_backend == "fake":
            from classlop.teams.fake import demo

            _backend = demo()
        else:
            from classlop.teams.service import GraphTeams

            _backend = GraphTeams(GraphClient(), records=GraphClient(token=app_token))
    return _backend


async def list_owned_teams() -> list[Team]:
    """The teams the Teacher owns."""
    return await backend().list_owned_teams()


async def link_team(team_id: str) -> Class:
    """Link a team as a Class and make its members who aren't owners Students."""
    return await backend().link_team(team_id)


async def get_class(class_id: str) -> Class:
    return await backend().get_class(class_id)


async def list_classes() -> list[Class]:
    return await backend().list_classes()


async def list_students(class_id: str) -> list[Student]:
    """Students and Former students (`former_since` set)."""
    return await backend().list_students(class_id)


async def sync_roster(class_id: str) -> None:
    """Bring the Class's Students in step with its team now."""
    await backend().sync_roster(class_id)


async def search_users(query: str) -> list[Candidate]:
    """Tenant users to pick as Students, by name."""
    return await backend().search_users(query)


async def create_class(name: str, student_user_ids: list[str]) -> Class:
    """Create a Private team (the Teacher as owner, the users as members) and link it."""
    return await backend().create_class(name, student_user_ids)


async def add_student(class_id: str, user_id: str) -> Student:
    return await backend().add_student(class_id, user_id)


async def remove_student(class_id: str, user_id: str) -> None:
    """Removes them from the team; they become a Former student."""
    await backend().remove_student(class_id, user_id)


async def rename_class(class_id: str, name: str) -> Class:
    """Renames the Class and its team."""
    return await backend().rename_class(class_id, name)


async def add_timetable(class_id: str, slots: list[Slot], school_year_end: date) -> None:
    """Enter the Class's Timetable: each slot becomes a recurring Teams event."""
    await backend().add_timetable(class_id, slots, school_year_end)


async def add_lesson(class_id: str, start: datetime, end: datetime, topic: str) -> Lesson:
    """Add a single Lesson; the Lesson topic is required."""
    return await backend().add_lesson(class_id, start, end, topic)


async def list_lessons(class_id: str) -> list[Lesson]:
    return await backend().list_lessons(class_id)


async def sync_calendar() -> None:
    """Bring Lessons in step with the Teacher's Teams calendar now."""
    await backend().sync_calendar()


async def list_calendar_questions() -> list[CalendarQuestion]:
    return await backend().list_calendar_questions()


async def answer_calendar_question(question_id: str, answer: str) -> None:
    await backend().answer_calendar_question(question_id, answer)


async def get_attendance(class_id: str, lesson_id: str) -> Attendance:
    """Each Student Present, Late or Absent with minutes, overrides applied, plus Unmatched
    attendees. States are None until the first fetch."""
    return await backend().get_attendance(class_id, lesson_id)


async def refresh_attendance(class_id: str, lesson_id: str) -> Attendance:
    """Fetch the Lesson's Attendance from Teams now."""
    return await backend().refresh_attendance(class_id, lesson_id)


async def fetch_due_attendance() -> int:
    return await backend().fetch_due_attendance()


async def override_attendance(
    class_id: str, lesson_id: str, student_id: str, state: AttendanceState | None
) -> None:
    """The Teacher's state for a Student; it survives every later fetch. None removes it."""
    await backend().override_attendance(class_id, lesson_id, student_id, state)


async def link_attendee(class_id: str, key: str, student_id: str) -> None:
    """Link an Unmatched attendee (by its `key`) to a Student, for this and later Lessons."""
    await backend().link_attendee(class_id, key, student_id)


async def lateness_threshold() -> timedelta:
    return await backend().lateness_threshold()


async def set_lateness_threshold(threshold: timedelta) -> None:
    """How long after a Lesson's start a first join still counts as on time, for all Classes."""
    await backend().set_lateness_threshold(threshold)


async def cancel_lessons(class_id: str, first: date, last: date) -> None:
    """Cancel every Lesson from `first` to `last` (a break); they keep their Lesson topic."""
    await backend().cancel_lessons(class_id, first, last)


async def change_slot(class_id: str, old: Slot, new: Slot, from_date: date) -> None:
    """Change a Timetable slot from a date: the old series ends the day before."""
    await backend().change_slot(class_id, old, new, from_date)


async def set_lesson_topic(class_id: str, lesson_id: str, topic: str) -> Lesson:
    """Set a Lesson's topic, which also becomes its Teams event title."""
    return await backend().set_lesson_topic(class_id, lesson_id, topic)


async def give_assignment(
    class_id: str, spec: AssignmentSpec, items_pdf: bytes, when: datetime | None = None
) -> Assignment:
    """Give an Assignment now or at `when`: post it in General and give each recipient a private
    hand-in folder and a chat message. Given once Teams accepts the post."""
    return await backend().give_assignment(class_id, spec, items_pdf, when)


async def get_assignment(assignment_id: str) -> Assignment:
    return await backend().get_assignment(assignment_id)


async def list_assignments(class_id: str) -> list[Assignment]:
    return await backend().list_assignments(class_id)


async def list_submissions(assignment_id: str) -> list[Submission]:
    return await backend().list_submissions(assignment_id)


async def deliver_assignment(assignment_id: str) -> int:
    """Retry the Students an Assignment has not reached; returns how many are still waiting."""
    return await backend().deliver_assignment(assignment_id)


async def give_again(assignment_id: str, when: datetime | None = None) -> Assignment:
    """Give a Draft that failed to be given, now or at `when`."""
    return await backend().give_again(assignment_id, when)


async def publish_scheduled(assignment_id: str, last_try: bool = False) -> Assignment:
    """Post a Scheduled Assignment; the job at its time calls this."""
    return await backend().publish_scheduled(assignment_id, last_try)


async def list_failed_gives() -> list[Assignment]:
    """Drafts that failed to be given, for the home screen."""
    return await backend().list_failed_gives()


async def poll_handins() -> int:
    """Turn what Students uploaded into Submissions and close what is due; the job calls this
    every 2 minutes."""
    return await backend().poll_handins()


async def close_due_assignments() -> int:
    """Close Open Assignments whose close time has come."""
    return await backend().close_due_assignments()
