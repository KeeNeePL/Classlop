"""Returning Feedback as plain functions: the real area and FakeTeams share them, so when a
Submission is returned and the words the Student reads cannot drift (ADR 0002)."""

from datetime import datetime, timedelta
from html import escape
from typing import Literal

from classlop.teams import assignments, ids
from classlop.teams.types import Assignment, SubmissionState

FOLDER = "Feedback"
# A schedule that fires in the past is refused, so one for a due time that has come waits a little.
LEAD = timedelta(minutes=1)

Step = Literal["skip", "mark", "return", "correct"]


def schedule_name(assignment_id: str) -> str:
    return f"teams.due:{assignment_id}"


def due_at(due: datetime, now: datetime) -> datetime:
    return max(due, now + LEAD)


def step(
    *,
    state: SubmissionState,
    late: bool,
    due_at: datetime,
    now: datetime,
    held: bool,
    pdf_key: str,
    sent: str | None,
) -> Step:
    """What a graded result does to a Submission: nothing, mark it Graded to wait for the due
    time or the Teacher, return it, or send a correction. `pdf_key` is the result's Feedback PDF
    ("" for none) and `sent` that of the last message to the Student (None if there was none).
    Only a Held result is kept back after the due time; a Late submission is returned on grading."""
    if state == "returned":
        return "correct" if not held and pdf_key != sent else "skip"
    if state not in ("handed_in", "graded"):
        return "skip"
    if held or not (late or now >= due_at):
        return "mark"
    return "return"


def attachment_name(a: Assignment) -> str:
    return f"Ocena - {assignments.safe(a.title)}.pdf"


def file_name(student_name: str) -> str:
    return f"{assignments.safe(student_name)}.pdf"


def message_html(a: Assignment, comment: str, corrected: bool, attachment_id: str | None) -> str:
    """The 1:1 chat message that returns Feedback; a correction says so."""
    lead = "Poprawiona ocena pracy" if corrected else "Ocena pracy"
    text = "<br>".join(escape(line) for line in comment.splitlines())
    attached = f'<attachment id="{attachment_id}"></attachment>' if attachment_id else ""
    return f"<p><b>{lead}: {escape(a.title)}</b></p><p>{text}</p>{attached}"


def common_mistakes_job(a: Assignment) -> tuple[str, dict]:
    """The `grading.common_mistakes` job for the due time; one per due time."""
    assignment_id = str(ids.as_uuid(a.id))
    return f"grading.common_mistakes:{assignment_id}@{a.due_at.isoformat()}", {
        "assignment_id": assignment_id
    }
