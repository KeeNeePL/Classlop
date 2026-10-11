"""The Class overview screen: one endpoint returns the ready overview of one Class."""

from typing import Annotated

from fastapi import APIRouter, Depends

from classlop.dashboard import auth, bank, class_read
from classlop.dashboard.classes import TheTeams
from classlop.dashboard.reports import ClassOverview, class_overview
from classlop.items import curriculum

router = APIRouter()


class OverviewResponse(ClassOverview):
    invented: bool


@router.get("/api/classes/{class_id}/overview")
async def overview(
    class_id: str, _: Annotated[auth.Me, Depends(auth.teacher)], t: TheTeams, pool: bank.TheBank
) -> OverviewResponse:
    read, invented = await class_read.read(class_id, t, pool)
    return OverviewResponse(
        **class_overview(read.data, curriculum()).model_dump(), invented=invented
    )
