"""How a Student's files become a Submission, as plain functions: the real area and FakeTeams
share them, so the rules cannot drift."""

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from classlop.teams import assignments, ids
from classlop.teams.types import Assignment, AssignmentState, SubmissionState

QUIET = timedelta(minutes=3)
# Files and folders of these Submissions are no longer read: the work went back or is not owed.
FROZEN: frozenset[SubmissionState] = frozenset({"returned", "missing", "excused"})
# A hand-in the Teacher has not yet sent back, and every state in which the Student has handed in.
HANDED_IN: tuple[SubmissionState, ...] = ("handed_in", "graded")
WITH_WORK: tuple[SubmissionState, ...] = (*HANDED_IN, "returned")


def takes_files(
    state: SubmissionState, assignment: AssignmentState, uploaded_at: datetime, close_at: datetime
) -> bool:
    """Whether a file uploaded at `uploaded_at` (server time) is part of the hand-in."""
    return state not in FROZEN and assignment == "open" and uploaded_at <= close_at


def signature(files: Iterable[tuple[str, datetime]]) -> str | None:
    """Identifies a file set by its files and when each was uploaded; None for no files."""
    parts = sorted(f"{file_id}@{uploaded_at.isoformat()}" for file_id, uploaded_at in files)
    return hashlib.sha1("\n".join(parts).encode()).hexdigest() if parts else None


class Settlement(NamedTuple):
    state: SubmissionState
    handed_in_at: datetime | None
    late: bool
    signature: str | None


def settle(
    *,
    state: SubmissionState,
    changed_at: datetime | None,
    files: list[tuple[str, datetime]],
    due_at: datetime,
    now: datetime,
    settled: tuple[str | None, datetime | None] = (None, None),
    force: bool = False,
) -> Settlement | None:
    """What the folder's files make of the Submission once they have been still for 3 minutes
    (at once if `force`), or None while they have not or the Submission takes no files. The
    caller compares the signature with the last settled one to tell a new hand-in from an
    unchanged one. The hand-in's time is the server time of the last upload of the files that
    remain, and it is Late by that time alone. Grading tells hand-ins apart by that time, so
    when other files with the same last upload were settled before (`settled`: their signature
    and time), the moment the change was seen stands in for it."""
    if state in FROZEN or changed_at is None or (not force and now < changed_at + QUIET):
        return None
    if not files:
        return Settlement("not_handed_in", None, False, None)
    last, sig = max(uploaded_at for _, uploaded_at in files), signature(files)
    return Settlement(
        "handed_in",
        changed_at if sig != settled[0] and last == settled[1] else last,
        last > due_at,
        sig,
    )


def becomes_missing(state: SubmissionState, former: bool, delivered: bool) -> bool:
    """At close, a Student who has not handed in is Missing, unless they left the Class before
    the Assignment ever reached them."""
    return state == "not_handed_in" and (delivered or not former)


def prefix(submission_id: str) -> str:
    """Where the copies of a Submission's files are kept in storage."""
    return f"teams/submissions/{submission_id}/"


def file_key(submission_id: str, uploaded_at: datetime, name: str) -> str:
    stamp = uploaded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix(submission_id)}{stamp}-{assignments.safe(name)}"


def grade_job(
    assignment: Assignment, submission_id: str, handed_in_at: datetime, files: list[str]
) -> tuple[str, dict]:
    """The key and payload of the `grading.grade` job for a settled hand-in. One hand-in makes
    one job, however often it is seen."""
    payload = {
        "submission_id": str(ids.as_uuid(submission_id)),
        "handed_in_at": handed_in_at.isoformat(),
        "assignment_id": str(ids.as_uuid(assignment.id)),
        "due_at": assignment.due_at.isoformat(),
        "items": [{"id": str(v), "number": n} for n, v in enumerate(assignment.item_versions, 1)],
        "files": files,
    }
    return f"grading.grade:{payload['submission_id']}@{payload['handed_in_at']}", payload
