"""The home screen's endpoint and the lapsed sign-in flag, over HTTP with the Teacher signed in.
The Lessons, problems and deadlines come from FakeTeams; AI-graded entries stay invented until
#82."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fake_bank import InMemoryBank
from fake_work import Offline, invented_class
from fastapi.testclient import TestClient
from sqlalchemy import delete
from tenant import Clock

from classlop import teams
from classlop.dashboard import auth, bank, classes, home
from classlop.dashboard.app import create_app
from classlop.shared import storage
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.models import Job
from classlop.teams.fake import FakeTeams

OPEN_MEDIUM_III = uuid.UUID(int=1001)


def signed_in(fake: FakeTeams | None = None, lapsed: bool | None = False) -> TestClient:
    """`lapsed` None asks the jobs table whether the sign-in lapsed."""
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    if lapsed is not None:
        app.dependency_overrides[auth.sign_in_lapsed] = lambda: lapsed
    items = InMemoryBank()
    app.dependency_overrides[bank.backend] = lambda: items
    app.dependency_overrides[classes.backend] = lambda: fake or FakeTeams()
    app.dependency_overrides[home.failed_gives] = lambda: [
        home.Entry(
            kind="give_failed",
            title="Nie udało się wydać pracy «Ciągi»",
            detail="Teams odrzucił publikację dla klasy 1A",
            link="/klasy/1a/prace/ciagi",
            action="Otwórz pracę",
        )
    ]
    return TestClient(app)


@pytest.fixture
async def own(monkeypatch) -> FakeTeams:
    """1A has a Lesson on now, two to come and an Open Assignment due tonight, handed in by one of
    its three Students; the team of 3C was deleted in Teams."""
    clock = Clock()
    clock.now = datetime.now(UTC)
    fake = FakeTeams(clock=clock)
    monkeypatch.setattr(teams, "_backend", fake)
    for module, name, replacement in Offline(InMemoryBank()).patches():
        monkeypatch.setattr(module, name, replacement)
    monkeypatch.setattr(storage, "put", lambda *_: None)
    klass = await invented_class(fake)
    now, minutes = clock.now, lambda m: timedelta(minutes=m)
    await fake.add_lesson(klass.id, now - minutes(10), now + minutes(35), "Funkcje")
    await fake.add_lesson(klass.id, now + minutes(180), now + minutes(225), "Ciągi")
    await fake.add_lesson(klass.id, now + minutes(1440), now + minutes(1485), "Potęgi")
    await fake.give_assignment(
        klass.id,
        teams.AssignmentSpec(
            title="Równania",
            type="homework",
            due_at=now + minutes(540),
            close_at=now + minutes(3000),
            item_ids=[OPEN_MEDIUM_III],
        ),
        b"%PDF-1.7 rownania",
    )
    ala = next(s.user_id for s in await fake.list_students(klass.id))
    fake.upload(ala, "strona-1.jpg", b"page one")
    clock.advance(minutes=4)
    await fake.poll_handins()
    gone = fake.add_team("3C")
    await fake.sync_roster((await fake.link_team(gone)).id)
    fake.delete_team(gone)
    await fake.sync_roster(next(c.id for c in await fake.list_classes() if c.team_id == gone))
    return fake


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


async def test_the_queue_puts_the_live_lesson_then_problems_then_the_rest(own):
    entries = signed_in(own, lapsed=True).get("/api/home").json()["entries"]

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
    assert entries[3]["title"] == "Zespół klasy 3C usunięto w Teams"


async def test_the_lessons_and_deadlines_come_from_teams(own):
    entries = signed_in(own).get("/api/home").json()["entries"]

    shown = {e["kind"]: (e["title"], e["detail"], e["action"]) for e in entries}
    assert shown["live_lesson"] == ("Trwa lekcja: klasa 1A", "Funkcje", "Dołącz w Teams")
    assert shown["next_lesson"] == ("Lekcja: klasa 1A", "Ciągi", "Otwórz lekcję")
    assert shown["deadline"] == (
        "Termin: Równania (1A)",
        "Praca domowa, oddane 1/3",
        "Otwórz pracę",
    )
    live = next(e for e in entries if e["kind"] == "live_lesson")
    assert live["link"].startswith("https://")
    assert "sign_in" not in shown


async def test_a_class_without_lessons_or_work_adds_nothing_to_the_queue():
    entries = signed_in().get("/api/home").json()["entries"]

    assert [e["kind"] for e in entries] == ["give_failed", "graded", "graded"]


def test_home_marks_what_is_invented():
    home = signed_in().get("/api/home").json()

    assert home["entries_invented"] is True
    assert home["sidebar_invented"] is True


def test_home_gives_the_sidebar_its_classes_and_flagged_count():
    home = signed_in().get("/api/home").json()

    assert [c["name"] for c in home["classes"]] == ["1A", "2C", "3B"]
    assert home["flagged_items"] == 4


async def test_times_go_out_as_utc(own):
    entries = signed_in(own).get("/api/home").json()["entries"]

    timed = [e["at"] for e in entries if e["at"]]
    assert timed and all(at.endswith("Z") for at in timed)


async def test_me_reports_a_lapsed_sign_in_while_a_job_waits_for_it(jobs_table):
    web = signed_in(lapsed=None)
    assert web.get("/api/me").json() == {"name": "Anna Nowak", "sign_in_lapsed": False}

    async with sessions().begin() as session:
        session.add(Job(id=uuid.uuid4(), kind="teams.whoami", status="waiting_for_sign_in"))

    assert await asyncio.to_thread(lambda: web.get("/api/me").json()["sign_in_lapsed"]) is True
