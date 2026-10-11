import uuid

from sqlalchemy import func, or_, select

from classlop.grading.models import GradedItem, GradedSubmission, Override
from classlop.shared.db import sessions


async def item_averages(
    assignment_ids: list[uuid.UUID],
) -> dict[tuple[uuid.UUID, uuid.UUID], float]:
    """How much of an Item's points the Class earned in each Assignment, 0 to 1, keyed by
    (Assignment, Item). It counts each Submission's newest hand-in with the Teacher's Overrides
    and leaves out Held Submissions until "Zatwierdź", as the Reports do. No entry where
    nothing is graded."""
    newest = (
        select(
            GradedSubmission.submission_id,
            func.max(GradedSubmission.handed_in_at).label("handed_in_at"),
        )
        .where(GradedSubmission.assignment_id.in_(assignment_ids))
        .group_by(GradedSubmission.submission_id)
        .subquery()
    )
    earned = func.sum(func.coalesce(Override.points, GradedItem.ai_points))
    available = func.sum(GradedItem.max_points)
    query = (
        select(GradedSubmission.assignment_id, GradedItem.item_id, earned, available)
        .join(
            newest,
            (GradedSubmission.submission_id == newest.c.submission_id)
            & (GradedSubmission.handed_in_at == newest.c.handed_in_at),
        )
        .join(
            GradedItem,
            (GradedItem.submission_id == GradedSubmission.submission_id)
            & (GradedItem.handed_in_at == GradedSubmission.handed_in_at),
        )
        .outerjoin(
            Override,
            (Override.submission_id == GradedItem.submission_id)
            & (Override.handed_in_at == GradedItem.handed_in_at)
            & (Override.item_id == GradedItem.item_id),
        )
        .where(
            GradedSubmission.status == "graded",
            or_(
                func.jsonb_array_length(GradedSubmission.held_reasons) == 0,
                GradedSubmission.approved_at.is_not(None),
            ),
        )
        .group_by(GradedSubmission.assignment_id, GradedItem.item_id)
        .having(available > 0)
    )
    async with sessions()() as session:
        rows = await session.execute(query)
    return {(a, i): float(e) / float(t) for a, i, e, t in rows if a is not None}
