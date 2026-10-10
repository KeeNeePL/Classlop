"""The Teacher's actions on a result, called by `dashboard`."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from classlop.grading.common_mistakes import request_common_mistakes
from classlop.grading.feedback import feedback_typesets, summarise, typesets
from classlop.grading.graph import announce, grade_fixed_item, rebuild_feedback
from classlop.grading.models import GradedItem, GradedSubmission, Override
from classlop.shared import jobs
from classlop.shared.db import sessions
from classlop.shared.llm import traced


class TooEarly(Exception):
    """A change before the due time; a Late submission's can be changed once graded."""


@traced("grading.override")
async def override(
    submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, points: int
) -> None:
    """Replace the AI's points on one Item; the AI's points stay beside the Override."""
    async with sessions().begin() as session:
        submission, item = await _changeable_item(session, submission_id, handed_in_at, item_id)
        if not 0 <= points <= item.max_points:
            raise ValueError(f"points must be 0 to {item.max_points}")
        await session.execute(
            insert(Override)
            .values(
                submission_id=submission_id,
                handed_in_at=handed_in_at,
                item_id=item_id,
                points=points,
            )
            .on_conflict_do_update(
                index_elements=["submission_id", "handed_in_at", "item_id"],
                set_={"points": points},
            )
        )
        await session.flush()
        await session.refresh(item, ["override_record"])
        # Points alone keep the summary: an Override stays cheap and quick.
        await _rebuild_feedback(submission)
    await _changed(submission)


@traced("grading.fix_transcription")
async def fix_transcription(
    submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, transcription: str
) -> None:
    """Grade one Item again from the fixed Transcription. Its Override and Feedback edit
    judged the misreading, so both go."""
    async with sessions().begin() as session:
        submission, item = await _changeable_item(session, submission_id, handed_in_at, item_id)
        await grade_fixed_item(item, transcription)
        item.edited_feedback = None
        await session.execute(
            delete(Override).where(
                Override.submission_id == submission_id,
                Override.handed_in_at == handed_in_at,
                Override.item_id == item_id,
            )
        )
        await session.flush()
        await session.refresh(item, ["override_record"])
        submission.summary = await summarise(submission.items)
        await _rebuild_feedback(submission)
    await _changed(submission)


@traced("grading.edit_feedback")
async def edit_feedback(
    submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, feedback: str
) -> None:
    """Reword one Item's Feedback; the AI's stays beside it. No free editing of the PDF."""
    if feedback and not await typesets(feedback):
        raise ValueError("the Feedback will not typeset; check the $...$ maths")
    async with sessions().begin() as session:
        submission, item = await _changeable_item(session, submission_id, handed_in_at, item_id)
        item.edited_feedback = feedback
        submission.summary = await summarise(submission.items)
        await _rebuild_feedback(submission)
    await _changed(submission)


async def approve(submission_id: uuid.UUID, handed_in_at: datetime) -> None:
    """Zatwierdź: clears the Spot-check flag and releases a Held Submission as graded."""
    async with sessions().begin() as session:
        submission = await _submission(session, submission_id, handed_in_at)
        # A failed result has no points to release; it is graded again instead.
        if submission.status == "failed":
            raise ValueError("a failed result is graded again, not approved")
        submission.approved_at = datetime.now(UTC)
    await _changed(submission)


async def grade_again(submission_id: uuid.UUID, handed_in_at: datetime) -> None:
    """Oceń ponownie: a successful run replaces the failed result."""
    async with sessions()() as session:
        submission = await _submission(session, submission_id, handed_in_at)
    if submission.status != "failed":
        raise ValueError("only a failed result is graded again")
    await jobs.enqueue("grading.grade", submission.grade_job)


async def _submission(
    session: AsyncSession, submission_id: uuid.UUID, handed_in_at: datetime
) -> GradedSubmission:
    # Locked: a change takes model calls, and a second change at the same time must wait.
    submission = await session.get(
        GradedSubmission, (submission_id, handed_in_at), with_for_update=True
    )
    if submission is None:
        raise LookupError(f"no result for {submission_id} handed in at {handed_in_at}")
    return submission


async def _changeable_item(
    session: AsyncSession, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID
) -> tuple[GradedSubmission, GradedItem]:
    submission = await _submission(session, submission_id, handed_in_at)
    if submission.status == "failed":
        raise ValueError("a failed result has no Items to change; grade it again")
    item = next((i for i in submission.items if i.item_id == item_id), None)
    if item is None:
        raise LookupError(f"no Item {item_id} in this result")
    # A Late submission is handed in after the due time, so it passes at once.
    due_at = submission.due_at
    if due_at is not None and datetime.now(UTC) < due_at:
        raise TooEarly(f"changes open at the due time, {due_at.isoformat()}")
    return submission, item


async def _rebuild_feedback(submission: GradedSubmission) -> None:
    untypeset = [i.number for i in submission.items if not await feedback_typesets(i)]
    await rebuild_feedback(submission, untypeset)


async def _changed(submission: GradedSubmission) -> None:
    await announce(submission.submission_id, submission.handed_in_at)
    if submission.assignment_id is not None:
        await request_common_mistakes(submission.assignment_id)
