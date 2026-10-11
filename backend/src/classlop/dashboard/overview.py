"""The Class overview screen: one endpoint returns the ready overview of one Class."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from classlop.dashboard import auth, bank, grader, invented
from classlop.dashboard.actions import refusing
from classlop.dashboard.classes import TheTeams
from classlop.dashboard.reports import ClassData, ClassOverview, Student, class_overview
from classlop.items import curriculum

router = APIRouter()


class OverviewResponse(ClassOverview):
    invented: bool


@router.get("/api/classes/{class_id}/overview")
async def overview(
    class_id: str,
    _: Annotated[auth.Me, Depends(auth.teacher)],
    t: TheTeams,
    pool: bank.TheBank,
    graded: grader.TheGrader,
) -> OverviewResponse:
    if (read := await invented.read(class_id, datetime.now(UTC), pool, graded)) is not None:
        view = class_overview(read.data, curriculum())
        return OverviewResponse(**view.model_dump(), invented=True)
    # A Class of the Teacher's own: its Students, until the Reports read its work (#81).
    with refusing():
        klass = await t.get_class(class_id)
        students = await t.list_students(class_id)
    data = ClassData(
        id=klass.id,
        name=klass.name,
        students=tuple(
            Student(id=s.id, name=s.display_name, former=s.former_since is not None)
            for s in students
        ),
        assignments=(),
    )
    return OverviewResponse(**class_overview(data, curriculum()).model_dump(), invented=False)
