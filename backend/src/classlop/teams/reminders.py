"""The Reminder as plain functions: when it fires, whether it is still due, who it counts and
what it says. The real area and FakeTeams share them, so the rules and the words cannot drift."""

from collections.abc import Iterable
from datetime import datetime, timedelta
from html import escape

from classlop.teams import assignments, submissions
from classlop.teams.types import Assignment, Student, Submission

ADVANCE = timedelta(hours=24)


def schedule_name(assignment_id: str) -> str:
    return f"teams.remind:{assignment_id}"


def fires_at(a: Assignment, now: datetime) -> datetime | None:
    """A day before the due time, if the Reminder is on, the Assignment was Given more than a
    day before it (so no quiz or exam is nagged about) and that moment is yet to come."""
    if not a.reminder_on or a.state not in assignments.LIVE or a.given_at is None:
        return None
    at = a.due_at - ADVANCE
    return at if a.given_at < at and now < at else None


def is_due(a: Assignment, now: datetime) -> bool:
    """Whether a fired schedule still means it: the Reminder is on, the Assignment is posted (a
    Scheduled one is not, and a Reminder before the post would be skipped, not posted late) and
    the due time is less than a day away but not past."""
    return a.reminder_on and a.state == "open" and a.due_at - ADVANCE <= now < a.due_at


def waiting(pairs: Iterable[tuple[Submission, Student]]) -> int:
    """How many Students have no hand-in: those who would be Missing if the Assignment closed
    now. Excused ones and Former students it never reached are not counted."""
    return sum(
        submissions.becomes_missing(s.state, bool(student.former_since), bool(s.notice_id))
        for s, student in pairs
    )


def count_text(count: int) -> str:
    """«7 osób» with the plural form Polish wants for `count`."""
    last, tens = count % 10, count % 100 // 10
    if count == 1:
        noun = "osoba"
    elif 2 <= last <= 4 and tens != 1:
        noun = "osoby"
    else:
        noun = "osób"
    return f"{count} {noun}"


def post_html(a: Assignment, count: int) -> str:
    """The post in General: which work, when it is due and how many have not handed in."""
    return (
        f"<p><b>Przypomnienie:</b> {escape(a.title)}, termin oddania: "
        f"{assignments.local_time(a.due_at)}.</p>"
        f"<p>Jeszcze nie oddało: {count_text(count)}.</p>"
    )
