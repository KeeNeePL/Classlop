"""The home screen's endpoint and the lapsed sign-in flag, over HTTP with the Teacher signed in."""

import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from classlop.dashboard import auth
from classlop.dashboard.app import create_app
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.models import Job


def signed_in() -> TestClient:
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    return TestClient(app)


@pytest.fixture
async def jobs_table():
    try:
        await asyncio.to_thread(migrate)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres")
    async with sessions().begin() as session:
        await session.execute(delete(Job))
    yield
    async with sessions().begin() as session:
        await session.execute(delete(Job))


def test_home_needs_a_session():
    assert TestClient(create_app()).get("/api/home").status_code == 401


def test_the_queue_puts_the_live_lesson_then_problems_then_the_rest():
    entries = signed_in().get("/api/home").json()["entries"]

    assert [e["kind"] for e in entries] == [
        "live_lesson",
        "sign_in",
        "give_failed",
        "team_removed",
        "graded",
        "graded",
        "next_lesson",
        "deadline",
    ]
    assert entries[1]["title"] == "Zaloguj się ponownie"
    assert entries[2]["title"].startswith("Nie udało się wydać pracy «")
    assert entries[3]["title"].startswith("Zespół klasy ") and entries[3]["title"].endswith(
        " usunięto w Teams"
    )


def test_home_marks_what_is_invented():
    home = signed_in().get("/api/home").json()

    assert home["entries_invented"] is True
    assert home["sidebar_invented"] is True


def test_home_gives_the_sidebar_its_classes_and_flagged_count():
    home = signed_in().get("/api/home").json()

    assert [c["name"] for c in home["classes"]] == ["1A", "2C", "3B"]
    assert home["flagged_items"] == 4


def test_times_go_out_as_utc():
    entries = signed_in().get("/api/home").json()["entries"]

    timed = [e["at"] for e in entries if e["at"]]
    assert timed and all(at.endswith("Z") for at in timed)


async def test_me_reports_a_lapsed_sign_in_while_a_job_waits_for_it(jobs_table):
    web = signed_in()
    assert web.get("/api/me").json() == {"name": "Anna Nowak", "sign_in_lapsed": False}

    async with sessions().begin() as session:
        session.add(Job(id=uuid.uuid4(), kind="teams.whoami", status="waiting_for_sign_in"))

    assert await asyncio.to_thread(lambda: web.get("/api/me").json()["sign_in_lapsed"]) is True
