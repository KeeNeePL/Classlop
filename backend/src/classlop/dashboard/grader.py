"""What the dashboard asks of `grading`: the Class's results in one read, the Common mistakes of an
Assignment, and the Teacher's actions. Tests and the Playwright server swap it."""

import uuid
from datetime import datetime
from typing import Annotated, Protocol

from fastapi import Depends

from classlop import grading


class Grader(Protocol):
    async def results(self, assignment_ids: list[uuid.UUID]) -> list[grading.Result]: ...
    async def common_mistakes(self, assignment_id: uuid.UUID) -> list[grading.ItemMistakes]: ...
    async def override(
        self, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, points: int
    ) -> None: ...
    async def fix_transcription(
        self,
        submission_id: uuid.UUID,
        handed_in_at: datetime,
        item_id: uuid.UUID,
        transcription: str,
    ) -> None: ...
    async def edit_feedback(
        self, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, feedback: str
    ) -> None: ...
    async def approve(self, submission_id: uuid.UUID, handed_in_at: datetime) -> None: ...
    async def grade_again(self, submission_id: uuid.UUID, handed_in_at: datetime) -> None: ...


class GradingArea:
    """`grading` as it is."""

    async def results(self, assignment_ids: list[uuid.UUID]) -> list[grading.Result]:
        return await grading.results(assignment_ids)

    async def common_mistakes(self, assignment_id: uuid.UUID) -> list[grading.ItemMistakes]:
        return await grading.common_mistakes(assignment_id)

    async def override(
        self, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, points: int
    ) -> None:
        await grading.override(submission_id, handed_in_at, item_id, points)

    async def fix_transcription(
        self,
        submission_id: uuid.UUID,
        handed_in_at: datetime,
        item_id: uuid.UUID,
        transcription: str,
    ) -> None:
        await grading.fix_transcription(submission_id, handed_in_at, item_id, transcription)

    async def edit_feedback(
        self, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, feedback: str
    ) -> None:
        await grading.edit_feedback(submission_id, handed_in_at, item_id, feedback)

    async def approve(self, submission_id: uuid.UUID, handed_in_at: datetime) -> None:
        await grading.approve(submission_id, handed_in_at)

    async def grade_again(self, submission_id: uuid.UUID, handed_in_at: datetime) -> None:
        await grading.grade_again(submission_id, handed_in_at)


def backend() -> Grader:
    return GradingArea()


TheGrader = Annotated[Grader, Depends(backend)]
