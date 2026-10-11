"""The Submission view: one Submission Item by Item, and the Teacher's actions on it, which
`grading` carries out."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from classlop import grading
from classlop.dashboard import auth, bank, grader, invented
from classlop.dashboard.actions import carry_out
from classlop.dashboard.reports import assignment_summary
from classlop.dashboard.reports.records import SubmissionState
from classlop.items import ItemVersion

router = APIRouter()
Teacher = Annotated[auth.Me, Depends(auth.teacher)]
Grader = grader.TheGrader


class ItemView(BaseModel):
    item_id: uuid.UUID
    number: int
    text: str
    max_points: int
    ai_points: int
    override: int | None
    points: int
    reading: grading.Reading
    drawing: bool
    doubt: bool
    # The Teacher's fixed Transcription when there is one, which the Item was graded from.
    transcription: str
    fixed: bool
    # The Teacher's wording when there is one.
    feedback: str
    edited: bool
    mistake: str | None
    verification_note: str | None


class Neighbour(BaseModel):
    student_id: str
    name: str


class SubmissionPage(BaseModel):
    class_name: str
    assignment_id: str
    assignment_title: str
    due: datetime
    student_id: str
    name: str
    former: bool
    state: SubmissionState
    late: bool
    # None while there is no result: nothing handed in yet.
    submission_id: uuid.UUID | None
    handed_in_at: datetime | None
    status: grading.Status | None
    held: bool
    spot_check: bool
    held_reasons: list[grading.Reason]
    spot_check_reasons: list[grading.Reason]
    earned: int | None
    available: int
    # #7: the Teacher's changes open at the due time; `grading` refuses earlier ones.
    changeable: bool
    items: list[ItemView]
    # The Submissions before and after this one in the Assignment page's order.
    previous: Neighbour | None
    next: Neighbour | None
    invented: bool


def item(i: grading.ItemResult, version: ItemVersion) -> ItemView:
    return ItemView(
        item_id=i.item_id,
        number=i.number,
        text=version.text,
        max_points=i.max_points,
        ai_points=i.ai_points,
        override=i.override,
        points=i.points,
        reading=i.reading,
        drawing=i.drawing,
        doubt=i.doubt,
        transcription=(
            i.ai_transcription if i.fixed_transcription is None else i.fixed_transcription
        ),
        fixed=i.fixed_transcription is not None,
        feedback=i.feedback if i.edited_feedback is None else i.edited_feedback,
        edited=i.edited_feedback is not None,
        mistake=i.mistake,
        verification_note=i.verification_note,
    )


@router.get("/api/classes/{class_id}/assignments/{assignment_id}/submissions/{student_id}")
async def submission(
    class_id: str,
    assignment_id: str,
    student_id: str,
    _: Teacher,
    pool: bank.TheBank,
    graded: Grader,
) -> SubmissionPage:
    now = datetime.now(UTC)
    if (read := await invented.read(class_id, now, pool, graded)) is None:
        raise HTTPException(404)
    data, versions, results = read
    assignment = next((a for a in data.assignments if a.id == assignment_id), None)
    if assignment is None:
        raise HTTPException(404)
    mine = next((s for s in assignment.submissions if s.student_id == student_id), None)
    if mine is None:
        raise HTTPException(404)
    student = next(s for s in data.students if s.id == student_id)
    result = results.get(invented.submission_id(assignment_id, student_id))
    order = [
        Neighbour(student_id=r.student_id, name=r.name)
        for r in assignment_summary(assignment, data.students, [], now).rows
        if r.state in invented.WITH_WORK
    ]
    at = next((n for n, r in enumerate(order) if r.student_id == student_id), None)
    pinned = versions[assignment_id]
    items = [item(i, pinned[i.number - 1]) for i in result.items] if result else []
    return SubmissionPage(
        class_name=data.name,
        assignment_id=assignment_id,
        assignment_title=assignment.title,
        due=assignment.due,
        student_id=student_id,
        name=student.name,
        former=student.former,
        state=mine.state,
        late=mine.late,
        submission_id=result.submission_id if result else None,
        handed_in_at=result.handed_in_at if result else None,
        status=result.status if result else None,
        held=bool(result and result.held),
        spot_check=bool(result and result.spot_check),
        held_reasons=result.held_reasons if result else [],
        spot_check_reasons=result.spot_check_reasons if result else [],
        earned=sum(i.points for i in items) if items else None,
        available=sum(i.points for i in assignment.items),
        changeable=now >= assignment.due,
        items=items,
        previous=order[at - 1] if at else None,
        next=order[at + 1] if at is not None and at + 1 < len(order) else None,
        invented=True,
    )


class HandIn(BaseModel):
    """Which hand-in of the Submission the change is to: the one the page showed."""

    handed_in_at: datetime


class Points(HandIn):
    points: int


class Transcription(HandIn):
    transcription: str


class Feedback(HandIn):
    feedback: str


ITEM = "/api/submissions/{submission_id}/items/{item_id}"


@router.post(f"{ITEM}/override", status_code=204)
async def override(
    submission_id: uuid.UUID, item_id: uuid.UUID, body: Points, _: Teacher, graded: Grader
) -> Response:
    return await carry_out(graded.override(submission_id, body.handed_in_at, item_id, body.points))


@router.post(f"{ITEM}/transcription", status_code=204)
async def fix_transcription(
    submission_id: uuid.UUID, item_id: uuid.UUID, body: Transcription, _: Teacher, graded: Grader
) -> Response:
    return await carry_out(
        graded.fix_transcription(submission_id, body.handed_in_at, item_id, body.transcription)
    )


@router.post(f"{ITEM}/feedback", status_code=204)
async def edit_feedback(
    submission_id: uuid.UUID, item_id: uuid.UUID, body: Feedback, _: Teacher, graded: Grader
) -> Response:
    return await carry_out(
        graded.edit_feedback(submission_id, body.handed_in_at, item_id, body.feedback)
    )


@router.post("/api/submissions/{submission_id}/approve", status_code=204)
async def approve(submission_id: uuid.UUID, body: HandIn, _: Teacher, graded: Grader) -> Response:
    return await carry_out(graded.approve(submission_id, body.handed_in_at))


@router.post("/api/submissions/{submission_id}/grade-again", status_code=204)
async def grade_again(
    submission_id: uuid.UUID, body: HandIn, _: Teacher, graded: Grader
) -> Response:
    return await carry_out(graded.grade_again(submission_id, body.handed_in_at))
