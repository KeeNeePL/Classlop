"""The Teacher's actions on a result, called by `dashboard`."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from classlop.grading.common_mistakes import request_common_mistakes
from classlop.grading.graph import announce, text_comment
from classlop.grading.models import GradedSubmission, Override
from classlop.shared.db import sessions


class TooEarly(Exception):
    """An Override before the due time; a Late submission's can be overridden once graded."""


async def override(
    submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, points: int
) -> None:
    """Replace the AI's points on one Item; the AI's points stay beside the Override."""
    async with sessions().begin() as session:
        submission = await _submission(session, submission_id, handed_in_at)
        item = next((i for i in submission.items if i.item_id == item_id), None)
        if item is None:
            raise LookupError(f"no Item {item_id} in this result")
        if not 0 <= points <= item.max_points:
            raise ValueError(f"points must be 0 to {item.max_points}")
        # A Late submission is handed in after the due time, so it passes at once.
        due_at = submission.due_at
        if due_at is not None and datetime.now(UTC) < due_at:
            raise TooEarly(f"Overrides open at the due time, {due_at.isoformat()}")
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
        submission.comment = text_comment(submission.items)
    await _changed(submission)


async def approve(submission_id: uuid.UUID, handed_in_at: datetime) -> None:
    """Zatwierdź: clears the Spot-check flag and releases a Held Submission as graded."""
    async with sessions().begin() as session:
        submission = await _submission(session, submission_id, handed_in_at)
        submission.approved_at = datetime.now(UTC)
    await _changed(submission)


async def _submission(
    session: AsyncSession, submission_id: uuid.UUID, handed_in_at: datetime
) -> GradedSubmission:
    submission = await session.get(GradedSubmission, (submission_id, handed_in_at))
    if submission is None:
        raise LookupError(f"no result for {submission_id} handed in at {handed_in_at}")
    return submission


async def _changed(submission: GradedSubmission) -> None:
    await announce(submission.submission_id, submission.handed_in_at)
    if submission.assignment_id is not None:
        await request_common_mistakes(submission.assignment_id)
