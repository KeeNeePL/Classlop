"""`grading.item_averages`: the average score of an Item in an Assignment, from stored results."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from classlop import grading
from classlop.grading.models import GradedItem, GradedSubmission, Override
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
async def stack():
    try:
        await asyncio.to_thread(migrate)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres")


async def submit(
    assignment: uuid.UUID,
    points: dict[uuid.UUID, tuple[int, int]],
    *,
    submission_id: uuid.UUID | None = None,
    status="graded",
    held=False,
    approved=False,
    override: dict[uuid.UUID, int] | None = None,
    at: datetime = NOW,
) -> uuid.UUID:
    """One graded Submission; `points` maps an Item to its (AI points, max points)."""
    submission_id = submission_id or uuid.uuid4()
    async with sessions().begin() as session:
        session.add(
            GradedSubmission(
                submission_id=submission_id,
                handed_in_at=at,
                assignment_id=assignment,
                status=status,
                held_reasons=[{"reason": "unsure", "items": [1]}] if held else [],
                spot_check_reasons=[],
                approved_at=NOW if approved else None,
                comment="",
                items=[
                    GradedItem(
                        item_id=item,
                        position=n,
                        number=n + 1,
                        ai_points=ai,
                        max_points=top,
                        reading="readable",
                        drawing=False,
                        doubt=False,
                        ai_transcription="",
                        feedback="",
                    )
                    for n, (item, (ai, top)) in enumerate(points.items())
                ],
            )
        )
    if override:
        async with sessions().begin() as session:
            for item, value in override.items():
                session.add(
                    Override(
                        submission_id=submission_id, handed_in_at=at, item_id=item, points=value
                    )
                )
    return submission_id


async def test_the_average_is_points_earned_over_points_available_after_overrides():
    a, x, y = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await submit(a, {x: (2, 2), y: (0, 2)})
    await submit(a, {x: (1, 2), y: (1, 2)}, override={x: 2})

    averages = await grading.item_averages([a])

    assert averages == {(a, x): 1.0, (a, y): 0.25}


async def test_held_and_unfinished_submissions_stay_out_until_approved():
    a, x = uuid.uuid4(), uuid.uuid4()
    await submit(a, {x: (2, 2)})
    await submit(a, {x: (0, 2)}, held=True)
    await submit(a, {x: (0, 2)}, status="failed")
    await submit(a, {x: (0, 2)}, status="in_progress")

    assert await grading.item_averages([a]) == {(a, x): 1.0}

    await submit(a, {x: (0, 2)}, held=True, approved=True)

    assert await grading.item_averages([a]) == {(a, x): 0.5}


async def test_an_assignment_nobody_was_graded_in_has_no_average():
    a, x = uuid.uuid4(), uuid.uuid4()
    await submit(a, {x: (0, 2)}, held=True)

    assert await grading.item_averages([a, uuid.uuid4()]) == {}
    assert await grading.item_averages([]) == {}


async def test_an_item_worth_no_points_has_no_average():
    a, x = uuid.uuid4(), uuid.uuid4()
    await submit(a, {x: (0, 0)})

    assert await grading.item_averages([a]) == {}


async def test_only_the_newest_hand_in_of_a_submission_counts():
    a, x = uuid.uuid4(), uuid.uuid4()
    first = await submit(a, {x: (0, 2)}, at=NOW - timedelta(hours=1))
    await submit(a, {x: (2, 2)}, submission_id=first)

    assert await grading.item_averages([a]) == {(a, x): 1.0}
