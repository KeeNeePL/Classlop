import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import and_, func, select

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
    doubt: bool
    ai_transcription: str
    fixed_transcription: str | None
    feedback: str
    edited_feedback: str | None
    mistake: str | None
    verification_note: str | None
    override: int | None
    # Effective points: the AI's until the Teacher overrides them.
    points: int = Field(validation_alias="effective_points")


class Result(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    submission_id: uuid.UUID
    handed_in_at: datetime
    status: Status
    held_reasons: list[Reason]
    spot_check_reasons: list[Reason]
    summary: str
    comment: str
    # The current Feedback PDF in storage; none when the Submission has nothing to typeset.
    pdf_key: str | None
    items: list[ItemResult]
    approved_at: datetime | None

    @computed_field
    @property
    def held(self) -> bool:
        return bool(self.held_reasons) and self.approved_at is None

    @computed_field
    @property
    def spot_check(self) -> bool:
        return bool(self.spot_check_reasons) and self.approved_at is None


async def result(submission_id: uuid.UUID, handed_in_at: datetime) -> Result | None:
    async with sessions()() as session:
        row = await session.get(GradedSubmission, (submission_id, handed_in_at))
    return Result.model_validate(row) if row else None


async def results(assignment_ids: list[uuid.UUID]) -> list[Result]:
    """The current result of every Submission of these Assignments: per Submission, its newest
    hand-in's, as a newer hand-in replaces the result before it. A fixed number of queries
    whatever the number of Assignments. Results graded before `assignment_id` was stored have
    none and are left out."""
    if not assignment_ids:
        return []
    newest = (
        select(GradedSubmission.submission_id, func.max(GradedSubmission.handed_in_at).label("at"))
        .where(GradedSubmission.assignment_id.in_(assignment_ids))
        .group_by(GradedSubmission.submission_id)
        .subquery()
    )
    async with sessions()() as session:
        rows = await session.scalars(
            select(GradedSubmission).join(
                newest,
                and_(
                    GradedSubmission.submission_id == newest.c.submission_id,
                    GradedSubmission.handed_in_at == newest.c.at,
                ),
            )
        )
        return [Result.model_validate(row) for row in rows]
