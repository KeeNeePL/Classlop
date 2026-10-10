"""Teacher sign-in: the routes over a stubbed `shared.auth`, then `shared.auth` itself with real
MSAL talking to a fake Microsoft and the token cache in the compose Postgres."""

import asyncio
import base64
import hashlib
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from classlop import teams
from classlop.dashboard.app import create_app
from classlop.shared import auth, jobs
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.models import TokenCache
from classlop.shared.settings import get_settings

TENANT, TEACHER, OTHER = "tenant-1", "teacher-oid", "other-oid"


@pytest.fixture(autouse=True)
def tenant(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "m365_tenant_id", TENANT)
    monkeypatch.setattr(s, "m365_client_id", "client-1")
    monkeypatch.setattr(s, "m365_teacher_oid", TEACHER)


def client() -> TestClient:
    # https: the session cookie is Secure.
    return TestClient(create_app(), base_url="https://testserver", follow_redirects=False)


@pytest.fixture
def stubbed(monkeypatch):
    resumed = []

    async def sign_in_flow(scopes):
        return {"auth_uri": "https://login.example/authorize", "state": "s1", "scope": scopes}

    async def complete_sign_in(flow, params):
        assert flow == {"state": "s1", "scope": teams.GRAPH_SCOPES}
        if params["code"] == "other":
            raise auth.NotAdmitted("someone@example.org")
        if params["code"] == "bad":
            raise auth.SignInFailed("invalid_grant")
        return {"oid": TEACHER, "tid": TENANT, "name": "Anna Nowak"}

    async def resume_waiting():
        resumed.append(True)
        return 0

    monkeypatch.setattr(auth, "sign_in_flow", sign_in_flow)
    monkeypatch.setattr(auth, "complete_sign_in", complete_sign_in)
    monkeypatch.setattr(jobs, "resume_waiting", resume_waiting)
    return resumed


def test_me_needs_a_session():
    assert client().get("/api/me").status_code == 401


def test_the_teacher_signs_in_and_out(stubbed):
    web = client()

    login = web.get("/auth/login")
    assert login.headers["location"] == "https://login.example/authorize"
    cookie = login.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("httponly", "secure", "samesite=lax"))

    callback = web.get("/auth/callback", params={"code": "teacher", "state": "s1"})
    assert (callback.status_code, callback.headers["location"]) == (307, "/")
    assert stubbed == [True]
    assert web.get("/api/me").json() == {"name": "Anna Nowak"}

    web.get("/auth/logout")
    assert web.get("/api/me").status_code == 401


def test_another_account_is_refused(stubbed):
    web = client()
    web.get("/auth/login")

    response = web.get("/auth/callback", params={"code": "other", "state": "s1"})

    assert response.status_code == 403
    assert "to konto nie ma dostępu" in response.text.lower()
    assert web.get("/api/me").status_code == 401
    assert stubbed == []


def test_a_failed_or_stale_callback_does_not_sign_in(stubbed):
    web = client()
    assert web.get("/auth/callback", params={"code": "teacher"}).status_code == 400

    web.get("/auth/login")
    assert web.get("/auth/callback", params={"code": "bad", "state": "s1"}).status_code == 400
    assert web.get("/api/me").status_code == 401


def test_the_frontend_falls_back_to_index_but_api_paths_do_not(monkeypatch, tmp_path):
    from classlop.dashboard import app as app_module

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<app-root></app-root>")
    (dist / "main.js").write_text("boot()")
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setattr(app_module, "FRONTEND", dist)
    web = client()

    assert web.get("/main.js").text == "boot()"
    assert "app-root" in web.get("/klasy/2b").text
    assert web.get("/api/nothing").status_code == 404
    assert web.get("/%2e%2e/secret.txt").text == "<app-root></app-root>"


def b64(value: dict | str) -> str:
    raw = value if isinstance(value, str) else json.dumps(value)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


class Response:
    def __init__(self, body: dict, status_code: int = 200):
        self.status_code, self.text, self.headers = status_code, json.dumps(body), {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeMicrosoft:
    """The endpoints MSAL calls: tenant discovery and the token endpoint."""

    def __init__(self):
        self.refresh_works, self.grants, self.refreshed, self.nonce = True, [], [], ""

    def get(self, url, params=None, headers=None, **kwargs):
        base = f"https://login.microsoftonline.com/{TENANT}"
        if "discovery/instance" in url:
            host = "login.microsoftonline.com"
            return Response(
                {
                    "tenant_discovery_endpoint": f"{base}/v2.0/.well-known/openid-configuration",
                    "metadata": [{"preferred_network": host, "aliases": [host]}],
                }
            )
        return Response(
            {
                "authorization_endpoint": f"{base}/oauth2/v2.0/authorize",
                "token_endpoint": f"{base}/oauth2/v2.0/token",
                "issuer": f"{base}/v2.0",
            }
        )

    def post(self, url, params=None, data=None, headers=None, **kwargs):
        data = data or {}
        self.grants.append(data["grant_type"])
        if data["grant_type"] == "refresh_token" and not self.refresh_works:
            return Response({"error": "invalid_grant", "error_description": "expired"}, 400)
        if data["grant_type"] == "refresh_token":
            oid = data["refresh_token"].removeprefix("refresh-")
            self.refreshed.append(oid)
        else:
            oid = OTHER if data.get("code") == "other" else TEACHER
        claims = {"oid": oid, "tid": TENANT, "name": "Anna Nowak", "aud": "client-1"}
        claims |= {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "exp": 2**31}
        claims |= {"preferred_username": f"{oid}@example.org", "sub": oid}
        claims["nonce"] = hashlib.sha256(self.nonce.encode()).hexdigest()
        return Response(
            {
                "token_type": "Bearer",
                "scope": "User.Read openid profile offline_access",
                "expires_in": 3600 if data["grant_type"] == "refresh_token" else -10,
                "access_token": f"access-{data['grant_type']}",
                "refresh_token": f"refresh-{oid}",
                "id_token": f"{b64({'alg': 'none'})}.{b64(claims)}.",
                "client_info": b64({"uid": oid, "utid": TENANT}),
            }
        )


@pytest.fixture
async def microsoft(monkeypatch):
    try:
        await asyncio.to_thread(migrate)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres")
    async with sessions().begin() as session:
        await session.execute(delete(TokenCache))
    fake = FakeMicrosoft()
    monkeypatch.setattr(auth, "_client", lambda: auth._build(fake))
    return fake


async def sign_in(microsoft: FakeMicrosoft, code: str) -> dict:
    flow = await auth.sign_in_flow(["User.Read"])
    microsoft.nonce = flow["nonce"]
    return await auth.complete_sign_in(flow, {"code": code, "state": flow["state"]})


async def test_no_one_signed_in_means_sign_in_required(microsoft):
    with pytest.raises(jobs.SignInRequired):
        await auth.graph_token(["User.Read"])


async def test_another_account_leaves_no_tokens(microsoft):
    with pytest.raises(auth.NotAdmitted):
        await sign_in(microsoft, "other")

    with pytest.raises(jobs.SignInRequired):
        await auth.graph_token(["User.Read"])


async def test_a_job_refreshes_the_teachers_token_from_the_stored_cache(microsoft):
    claims = await sign_in(microsoft, "teacher")
    assert (claims["oid"], claims["name"]) == (TEACHER, "Anna Nowak")
    # As in another process: nothing in memory, only what Postgres holds.
    auth._tokens.deserialize(None)

    # The code's access token came back expired, so the refresh token is used.
    assert await auth.graph_token(["User.Read"]) == "access-refresh_token"
    assert microsoft.grants == ["authorization_code", "refresh_token"]


async def test_a_job_uses_the_teachers_tokens_when_another_account_is_cached(
    microsoft, monkeypatch
):
    # A leftover from before the Teacher was configured, cached first.
    monkeypatch.setattr(get_settings(), "m365_teacher_oid", OTHER)
    await sign_in(microsoft, "other")
    monkeypatch.setattr(get_settings(), "m365_teacher_oid", TEACHER)
    await sign_in(microsoft, "teacher")

    assert await auth.graph_token(["User.Read"]) == "access-refresh_token"
    assert microsoft.refreshed == [TEACHER]


async def test_a_lapsed_refresh_token_means_sign_in_required(microsoft):
    await sign_in(microsoft, "teacher")
    microsoft.refresh_works = False

    with pytest.raises(jobs.SignInRequired):
        await auth.graph_token(["User.Read"])
