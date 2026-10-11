"""Changing a Given Assignment as plain functions: the real area and FakeTeams share the rules and
the words Students read, so they cannot drift."""

from datetime import datetime

from classlop.teams import assignments, cards, submissions
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


def due_moved(a: Assignment) -> dict:
    """The reply in the post's thread."""
    due = assignments.local_time(a.due_at)
    return cards.message(
        f"Zmiana terminu: nowy termin oddania to {due}.",
        "Zmiana terminu",
        a.title,
        [cards.facts([("Nowy termin oddania", due)])],
    )


def cancelled(title: str) -> dict:
    """The chat message to each recipient of a deleted Assignment."""
    return cards.message(
        f"Praca «{title}» została anulowana.",
        "Praca anulowana",
        title,
        [cards.text("Tej pracy nie trzeba już oddawać.")],
    )
