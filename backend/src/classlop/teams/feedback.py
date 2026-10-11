"""Returning Feedback as plain functions: the real area and FakeTeams share them, so when a
Submission is returned and the words the Student reads cannot drift (ADR 0002)."""

import re
from datetime import datetime, timedelta
from typing import Literal

from classlop import grading
from classlop.teams import assignments, cards, ids, submissions
from classlop.teams.types import Assignment, SubmissionState

FOLDER = "Feedback"
# A schedule that fires in the past is refused, so one for a due time that has come waits a little.
LEAD = timedelta(minutes=1)
# A line of points in a Feedback comment, as `grading.text_comment` writes it.
_ITEM = re.compile(r"(Zadanie \d+): (.+)")

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
    if state not in submissions.HANDED_IN:
        return "skip"
    if held or not (late or now >= due_at):
        return "mark"
    return "return"


def attachment_name(a: Assignment) -> str:
    return f"Ocena - {assignments.safe(a.title)}.pdf"


def file_name(student_name: str) -> str:
    return f"{assignments.safe(student_name)}.pdf"


def message(a: Assignment, comment: str, corrected: bool, files: list[dict]) -> dict:
    """The 1:1 chat message that returns Feedback, with the PDF in `files`; a correction says so."""
    lead = "Poprawiona ocena pracy" if corrected else "Ocena pracy"
    return cards.message(f"{lead}: {a.title}", lead, a.title, _comment(comment), files=files)


def _comment(comment: str) -> list[dict]:
    """The paragraphs of `grading.text_comment`: the points per Item as a table, a heading over
    the topics to revise, the AI line in small print; anything else as it is."""
    blocks = []
    for n, paragraph in enumerate(comment.strip().split("\n\n")):
        lines = paragraph.splitlines()
        rest = {"separator": True, "spacing": "Medium"} if n > 1 else {}
        if all(_ITEM.match(line) for line in lines):
            blocks.append(cards.facts([_ITEM.match(line).groups() for line in lines], **rest))
        elif len(lines) > 1 and lines[0].endswith(":"):
            blocks.append(cards.text(lines[0].removesuffix(":"), weight="Bolder", **rest))
            blocks += [cards.text(f"• {line.lstrip('- ')}", spacing="None") for line in lines[1:]]
        elif paragraph == grading.AI_LINE:
            blocks.append(cards.text(paragraph, size="Small", isSubtle=True, **rest))
        else:
            blocks.append(cards.text(paragraph, **rest))
    return blocks


def common_mistakes_job(a: Assignment) -> tuple[str, dict]:
    """The `grading.common_mistakes` job for the due time; one per due time."""
    assignment_id = str(ids.as_uuid(a.id))
    return f"grading.common_mistakes:{assignment_id}@{a.due_at.isoformat()}", {
        "assignment_id": assignment_id
    }
