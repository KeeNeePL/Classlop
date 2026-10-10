import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import exists, select

from classlop import teams
from classlop.shared import auth, jobs
from classlop.shared.db import sessions
from classlop.shared.models import Job

log = logging.getLogger(__name__)
router = APIRouter()

RETRY = '<p>{}</p><p><a href="/auth/login">Zaloguj się ponownie</a></p>'


class Me(BaseModel):
    name: str


class MeView(Me):
    sign_in_lapsed: bool


def teacher(request: Request) -> Me:
    if "account" not in request.session:
        raise HTTPException(401)
    return Me(name=request.session["name"])


@router.get("/auth/login", include_in_schema=False)
async def login(request: Request) -> RedirectResponse:
    flow = await auth.sign_in_flow(teams.GRAPH_SCOPES)
    # The cookie carries the flow to the callback; auth_uri is only needed now.
    request.session["flow"] = {k: v for k, v in flow.items() if k != "auth_uri"}
    return RedirectResponse(flow["auth_uri"])


@router.get("/auth/callback", include_in_schema=False)
async def callback(request: Request):
    flow = request.session.pop("flow", None)
    try:
        if flow is None:
            raise auth.SignInFailed("no sign-in in progress")
        claims = await auth.complete_sign_in(flow, dict(request.query_params))
    except auth.NotAdmitted as exc:
        log.warning("sign-in refused for %s", exc)
        return HTMLResponse(RETRY.format("To konto nie ma dostępu."), status_code=403)
    except auth.SignInFailed as exc:
        log.warning("sign-in failed: %s", exc)
        return HTMLResponse(RETRY.format("Logowanie nie powiodło się."), status_code=400)
    request.session["account"] = f"{claims['oid']}.{claims['tid']}"
    request.session["name"] = claims.get("name", "")
    await jobs.resume_waiting()
    return RedirectResponse("/")


@router.get("/auth/logout", include_in_schema=False)
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/")


async def sign_in_lapsed() -> bool:
    """A job is parked until the Teacher signs in again."""
    async with sessions()() as session:
        return bool(
            await session.scalar(select(exists().where(Job.status == "waiting_for_sign_in")))
        )


@router.get("/api/me")
async def me(
    current: Annotated[Me, Depends(teacher)], lapsed: Annotated[bool, Depends(sign_in_lapsed)]
) -> MeView:
    return MeView(name=current.name, sign_in_lapsed=lapsed)
