"""Changing a Given Assignment as plain functions: the real area and FakeTeams share the rules and
the words Students read, so they cannot drift."""

from datetime import datetime
from html import escape

from classlop.teams import assignments, submissions
from classlop.teams.types import Assignment, Submission


def moved(
    a: Assignment, due_at: datetime | None, close_at: datetime | None
) -> tuple[datetime, datetime]:
    """The due and close times after a change, which only a Given Assignment that is not yet
    Closed takes."""
    if a.state not in assignments.LIVE:
        raise ValueError("only a Scheduled or Open Assignment changes its times")
    due, close = due_at or a.due_at, close_at or a.close_at
    if close < due:
        raise ValueError("an Assignment cannot close before it is due")
    return due, close


def note(reason: str | None) -> str | None:
    """The Teacher's private reason for an Excused Submission, None if there is none."""
    return (reason or "").strip() or None


def is_late(handed_in_at: datetime, due_at: datetime) -> bool:
    return handed_in_at > due_at


def worked_on(submission: Submission, uploaded: bool) -> bool:
    """Whether the Student has handed anything in: a settled hand-in, or files in their folder that
    have not settled yet (`uploaded`)."""
    return uploaded or submission.state in submissions.WITH_WORK or bool(submission.files)


def check_deletable(submissions: list[Submission], uploaded: set[str]) -> None:
    if any(worked_on(s, s.id in uploaded) for s in submissions):
        raise ValueError("an Assignment that has been handed in cannot be deleted")


def due_moved_html(due_at: datetime) -> str:
    """The reply in the post's thread."""
    return f"<p>Zmiana terminu: nowy termin oddania to {assignments.local_time(due_at)}.</p>"


def cancelled_html(title: str) -> str:
    """The chat message to each recipient of a deleted Assignment."""
    return f"<p>Praca «{escape(title)}» została anulowana.</p>"
