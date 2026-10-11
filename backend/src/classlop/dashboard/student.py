"""The Student report with the Teacher's Note, and the Suggested grade thresholds on Ustawienia."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator

from classlop.dashboard import auth, invented, store
from classlop.dashboard.reports import StudentReport, student_report
from classlop.dashboard.reports.grades import check_thresholds
from classlop.items import curriculum

router = APIRouter()
Teacher = Annotated[auth.Me, Depends(auth.teacher)]
Kept = Annotated[store.Store, Depends(store.backend)]


class StudentPage(StudentReport):
    class_name: str
    # The Teacher's own, never in any export.
    note: str
    invented: bool


@router.get("/api/classes/{class_id}/students/{student_id}/report")
async def report(
    class_id: str,
    student_id: str,
    kept: Kept,
    _: Teacher,
    start: datetime | None = None,
    end: datetime | None = None,
) -> StudentPage:
    """`start` and `end` bound the period by due time; leaving both out means everything."""
    now = datetime.now(UTC)
    if (name := invented.class_name(class_id, now)) is None:
        raise HTTPException(404)
    data = invented.class_data(class_id, name, now)
    if student_id not in {s.id for s in data.students}:
        raise HTTPException(404)
    view = student_report(data, student_id, curriculum(), start, end, await kept.thresholds())
    return StudentPage(
        **view.model_dump(),
        class_name=name,
        note=await kept.note(class_id, student_id),
        invented=True,
    )


class Note(BaseModel):
    text: str


@router.put("/api/classes/{class_id}/students/{student_id}/note", status_code=204)
async def save_note(class_id: str, student_id: str, body: Note, kept: Kept, _: Teacher) -> Response:
    now = datetime.now(UTC)
    if (name := invented.class_name(class_id, now)) is None or student_id not in {
        s.id for s in invented.class_data(class_id, name, now).students
    }:
        raise HTTPException(404)
    await kept.save_note(class_id, student_id, body.text)
    return Response(status_code=204)


class Thresholds(BaseModel):
    """The lowest percent for grades 2 to 6."""

    percents: list[int]

    @field_validator("percents")
    @classmethod
    def ranges(cls, percents: list[int]) -> list[int]:
        check_thresholds(percents)
        return percents


@router.get("/api/settings/thresholds")
async def thresholds(kept: Kept, _: Teacher) -> Thresholds:
    return Thresholds(percents=await kept.thresholds())


@router.put("/api/settings/thresholds", status_code=204)
async def save_thresholds(body: Thresholds, kept: Kept, _: Teacher) -> Response:
    await kept.save_thresholds(body.percents)
    return Response(status_code=204)
