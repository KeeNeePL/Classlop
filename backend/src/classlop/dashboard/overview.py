"""The Class overview screen: one endpoint returns the ready overview of one Class."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from classlop.dashboard import auth, invented
from classlop.dashboard.reports import ClassOverview, class_overview
from classlop.items import curriculum

router = APIRouter()


class OverviewResponse(ClassOverview):
    invented: bool


@router.get("/api/classes/{class_id}/overview")
async def overview(class_id: str, _: Annotated[auth.Me, Depends(auth.teacher)]) -> OverviewResponse:
    now = datetime.now(UTC)
    if (name := invented.class_name(class_id, now)) is None:
        raise HTTPException(404)
    view = class_overview(invented.class_data(class_id, name, now), curriculum())
    return OverviewResponse(**view.model_dump(), invented=True)
