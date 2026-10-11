"""The Assignment page: the Assignment summary with its CSV export, and the three changes the
Teacher makes to a Given Assignment, which `teams` carries out."""

import csv
import io
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from classlop import grading, teams
from classlop.dashboard import auth, invented
from classlop.dashboard.reports import AssignmentSummary, Mistake, Student, assignment_summary
from classlop.shared.jobs import SignInRequired

router = APIRouter()

STATES = {
    "not_handed_in": "nie oddano",
    "handed_in": "oddano, ocenia AI",
    "graded": "ocenione",
    "returned": "zwrócone",
    "missing": "brak pracy",
    "excused": "zwolniony",
}
HELD = "czeka na sprawdzenie"


class AssignmentPage(AssignmentSummary):
    class_name: str
    invented: bool


def mistakes(found: list[grading.ItemMistakes]) -> list[Mistake]:
    return [
        Mistake(number=i.number, description=m.description, count=m.count)
        for i in found
        for m in i.mistakes
    ]


def page(class_id: str, assignment_id: str) -> tuple[AssignmentPage, tuple[Student, ...]]:
    """The page, and the Class's Students in their order."""
    now = datetime.now(UTC)
    if (name := invented.class_name(class_id, now)) is None:
        raise HTTPException(404)
    data = invented.class_data(class_id, name, now)
    found = next((a for a in data.assignments if a.id == assignment_id), None)
    if found is None:
        raise HTTPException(404)
    view = assignment_summary(found, data.students, mistakes(invented.common_mistakes(found)), now)
    return AssignmentPage(**view.model_dump(), class_name=name, invented=True), data.students


@router.get("/api/classes/{class_id}/assignments/{assignment_id}")
async def assignment(
    class_id: str, assignment_id: str, _: Annotated[auth.Me, Depends(auth.teacher)]
) -> AssignmentPage:
    return page(class_id, assignment_id)[0]


@router.get(
    "/api/classes/{class_id}/assignments/{assignment_id}/csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def assignment_csv(
    class_id: str, assignment_id: str, _: Annotated[auth.Me, Depends(auth.teacher)]
) -> Response:
    """One row per recipient in the Class's order, for typing the grades into the e-gradebook.
    Semicolons and a BOM, so Excel opens it in Polish."""
    view, students = page(class_id, assignment_id)
    order = {s.id: n for n, s in enumerate(students)}
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        ["Uczeń", "Punkty", "Maks.", "Procent", "Proponowana ocena", "Stan", "Spóźniona"]
    )
    for r in sorted(view.rows, key=lambda r: order[r.student_id]):
        scored = r.percent is not None
        writer.writerow(
            [
                r.name,
                r.earned if scored else "",
                r.available if scored else "",
                f"{r.percent}%" if scored else "",
                r.suggested_grade if scored else "",
                HELD if r.held else STATES[r.state],
                "tak" if r.late else "nie",
            ]
        )
    name = quote(f"{view.title} ({view.class_name}).csv")
    return Response(
        "﻿" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=praca.csv; filename*=UTF-8''{name}"},
    )


class Times(BaseModel):
    due_at: datetime | None = None
    close_at: datetime | None = None


class Recipients(BaseModel):
    student_ids: list[str]


async def through_teams(change: Awaitable[object]) -> Response:
    """What `teams` refuses becomes an HTTP error the screen can show."""
    try:
        await change
    except LookupError as e:
        raise HTTPException(404) from e
    except SignInRequired as e:
        # The screen's interceptor answers a 401 with "Zaloguj się ponownie".
        raise HTTPException(401) from e
    except (ValueError, teams.ClassReadOnly) as e:
        raise HTTPException(409, str(e) or None) from e
    return Response(status_code=204)


@router.post("/api/assignments/{assignment_id}/times", status_code=204)
async def change_times(
    assignment_id: str, times: Times, _: Annotated[auth.Me, Depends(auth.teacher)]
) -> Response:
    return await through_teams(teams.change_times(assignment_id, times.due_at, times.close_at))


@router.post("/api/assignments/{assignment_id}/recipients", status_code=204)
async def add_recipients(
    assignment_id: str, body: Recipients, _: Annotated[auth.Me, Depends(auth.teacher)]
) -> Response:
    return await through_teams(teams.add_recipients(assignment_id, body.student_ids))


@router.delete("/api/assignments/{assignment_id}", status_code=204)
async def delete_assignment(
    assignment_id: str, _: Annotated[auth.Me, Depends(auth.teacher)]
) -> Response:
    return await through_teams(teams.delete_assignment(assignment_id))
