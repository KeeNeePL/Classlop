"""Opt-in smoke tests against the demo tenant: `uv run pytest -m live`. They need the compose
stand-ins, the Teacher signed in to Classlop since the scopes in GRAPH_SCOPES were granted, and
M365_STUDENT_UPNS and M365_STUDENT_PASSWORDS (two Students) in .env. They create a team named
"Klasa live-test ..." in the demo tenant and delete it at the end. Invented users only."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import msal
import pytest
from dotenv import dotenv_values

from classlop import items, teams
from classlop.shared.jobs import SignInRequired
from classlop.shared.settings import get_settings
from classlop.teams.graph import GraphClient, GraphError
from classlop.teams.service import GraphTeams

pytestmark = pytest.mark.live


def _students() -> list[tuple[str, str]]:
    env = {**dotenv_values("../.env"), **dotenv_values(".env")}
    upns = (env.get("M365_STUDENT_UPNS") or "").split(",")
    passwords = (env.get("M365_STUDENT_PASSWORDS") or "").split(",")
    if len(upns) < 2 or len(passwords) < 2 or not upns[0]:
        pytest.skip("M365_STUDENT_UPNS and M365_STUDENT_PASSWORDS name no two Students")
    return list(zip(upns, passwords, strict=False))[:2]


def _student_token(upn: str, password: str) -> str:
    s = get_settings()
    app = msal.ConfidentialClientApplication(
        s.m365_client_id,
        client_credential=s.m365_client_secret.get_secret_value() if s.m365_client_secret else None,
        authority=f"https://login.microsoftonline.com/{s.m365_tenant_id}",
    )
    result = app.acquire_token_by_username_password(
        upn, password, scopes=["https://graph.microsoft.com/Files.ReadWrite.All"]
    )
    if "access_token" not in result:
        pytest.skip(f"{upn} cannot sign in by password: {result.get('error_description')}")
    return result["access_token"]


async def test_a_student_sees_only_their_own_folder(monkeypatch):
    (jan_upn, jan_password), (ewa_upn, ewa_password) = _students()
    jan_token, ewa_token = await asyncio.gather(
        asyncio.to_thread(_student_token, jan_upn, jan_password),
        asyncio.to_thread(_student_token, ewa_upn, ewa_password),
    )

    async def no_items(item_ids, assignment_id, class_id, given_at):
        return [uuid.uuid4() for _ in item_ids]

    monkeypatch.setattr(items, "give", no_items)
    area = GraphTeams(GraphClient())
    try:
        users = {u.upn.lower(): u for q in (jan_upn, ewa_upn) for u in await area.search_users(q)}
    except SignInRequired:
        pytest.skip("the Teacher has not signed in to Classlop with the current scopes")
    suffix = uuid.uuid4().hex[:6]
    klass = await area.create_class(
        f"Klasa live-test {suffix}",
        [users[jan_upn.lower()].user_id, users[ewa_upn.lower()].user_id],
    )
    try:
        now = datetime.now(UTC)
        given = await area.give_assignment(
            klass.id,
            teams.AssignmentSpec(
                title=f"Zestaw live-test {suffix}",
                type="homework",
                due_at=now + timedelta(days=2),
                close_at=now + timedelta(days=3),
                item_ids=[uuid.uuid4()],
            ),
            b"%PDF-1.7 live smoke test",
        )
        assert given.state == "open"
        mine = {s.student_id: s for s in await area.list_submissions(given.id)}
        students = {s.upn.lower(): s for s in await area.list_students(klass.id)}
        jan, ewa = (mine[students[u.lower()].id] for u in (jan_upn, ewa_upn))
        assert jan.notice_id and ewa.notice_id and jan.folder_id and ewa.folder_id
        teacher = GraphClient()
        drive = (await teacher.get("/me/drive"))["id"]

        async def reads(token: str, folder_id: str) -> int:
            student = GraphClient(token=_const(token))
            try:
                await student.get(f"/drives/{drive}/items/{folder_id}")
            except GraphError as error:
                return error.status
            return 200

        assert await reads(jan_token, jan.folder_id) == 200
        assert await reads(ewa_token, ewa.folder_id) == 200
        assert await reads(jan_token, ewa.folder_id) in (403, 404)
        assert await reads(ewa_token, jan.folder_id) in (403, 404)
    finally:
        teacher = GraphClient()
        await teacher.request("DELETE", f"/groups/{klass.team_id}")
        try:
            root = await teacher.get(f"/me/drive/root:/Classlop/{klass.name}")
            await teacher.request("DELETE", f"/me/drive/items/{root['id']}")
        except GraphError:
            pass


def _const(token: str):
    async def get() -> str:
        return token

    return get
