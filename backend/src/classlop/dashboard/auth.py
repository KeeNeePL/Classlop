from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from classlop import teams
from classlop.shared import auth, jobs

router = APIRouter()

RETRY = '<p>{}</p><p><a href="/auth/login">Zaloguj się ponownie</a></p>'


class Me(BaseModel):
    name: str


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
    except auth.NotAdmitted:
        return HTMLResponse(RETRY.format("To konto nie ma dostępu."), status_code=403)
    except auth.SignInFailed:
        return HTMLResponse(RETRY.format("Logowanie nie powiodło się."), status_code=400)
    request.session["account"] = f"{claims['oid']}.{claims['tid']}"
    request.session["name"] = claims.get("name", "")
    await jobs.resume_waiting()
    return RedirectResponse("/")


@router.get("/auth/logout", include_in_schema=False)
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/")


@router.get("/api/me")
async def me(current: Annotated[Me, Depends(teacher)]) -> Me:
    return current
