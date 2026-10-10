import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from classlop.grading.models import GradedSubmission, Reading, Status
from classlop.shared.db import sessions


class Reason(BaseModel):
    """Why a Submission is Held or flagged, with the numbers of the Items that caused it."""

    reason: str
    items: list[int]


class ItemResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_id: uuid.UUID
    number: int
    ai_points: int
    max_points: int
    reading: Reading
    drawing: bool
    ai_transcription: str

    @computed_field
    @property
    def points(self) -> int:
        """Effective points: the AI's until the Teacher overrides them."""
        return self.ai_points


class Result(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    submission_id: uuid.UUID
    handed_in_at: datetime
    status: Status
    held_reasons: list[Reason]
    spot_check_reasons: list[Reason]
    comment: str
    items: list[ItemResult]

    @computed_field
    @property
    def held(self) -> bool:
        return bool(self.held_reasons)

    @computed_field
    @property
    def spot_check(self) -> bool:
        return bool(self.spot_check_reasons)


async def result(submission_id: uuid.UUID, handed_in_at: datetime) -> Result | None:
    async with sessions()() as session:
        row = await session.get(GradedSubmission, (submission_id, handed_in_at))
    return Result.model_validate(row) if row else None
