"""The Reports of a Class of the Teacher's own, read from `teams` (FakeTeams) in one call per
Class; the bank is in memory and nothing is graded yet."""

import uuid
from datetime import timedelta

import pytest
from e2e_app import create
from fake_work import Offline, invented_class
from fastapi.testclient import TestClient
from tenant import Clock

from classlop import teams
from classlop.dashboard import bank, classes
from classlop.shared import storage
from classlop.teams.fake import FakeTeams

OPEN_MEDIUM_III = uuid.UUID(int=1001)  # 2 points


class CountingTeams(FakeTeams):
    def __init__(self, clock):
        super().__init__(clock=clock)
        self.reads: list[str] = []

    async def read_class(self, class_id: str) -> teams.ClassRead:
        self.reads.append(class_id)
        return await super().read_class(class_id)


class Class:
    def __init__(self, web: TestClient, fake: CountingTeams, class_id: str, assignment_id: str):
        self.web, self.fake, self.id, self.assignment_id = web, fake, class_id, assignment_id

    def get(self, path: str):
        self.fake.reads.clear()
        got = self.web.get(f"/api/classes/{self.id}/{path}")
        assert got.status_code == 200, got.text
        assert self.fake.reads == [self.id]
        return got.json()

    def student(self, name: str) -> str:
        return next(s["id"] for s in self.get("overview")["students"] if s["name"] == name)


@pytest.fixture
async def klass(monkeypatch):
    """Ala attends the Lesson, Bartek hands in and Celina has left the Class."""
    app = create()
    items = app.dependency_overrides[bank.backend]()
    clock = Clock()
    fake = CountingTeams(clock)
    app.dependency_overrides[classes.backend] = lambda: fake
    for module, name, replacement in Offline(items).patches():
        monkeypatch.setattr(module, name, replacement)
    monkeypatch.setattr(storage, "put", lambda *_: None)
    made = await invented_class(fake)
    users = {s.display_name: s.user_id for s in await fake.list_students(made.id)}
    given = await fake.give_assignment(
        made.id,
        teams.AssignmentSpec(
            title="Równania",
            type="homework",
            due_at=clock.now + timedelta(days=7),
            close_at=clock.now + timedelta(days=9),
            item_ids=[OPEN_MEDIUM_III],
        ),
        b"%PDF-1.7 rownania",
    )
    start = clock.now + timedelta(hours=1)
    lesson = await fake.add_lesson(made.id, start, start + timedelta(minutes=45), "Równania")
    fake.attend(
        lesson.join_url,
        [(users["Ala Kowalska"], "Ala Kowalska", start, start + timedelta(minutes=40))],
    )
    clock.advance(hours=2)
    await fake.refresh_attendance(made.id, lesson.id)
    fake.upload(users["Bartek Nowicki"], "strona-1.jpg", b"page one")
    clock.advance(minutes=4)
    await fake.poll_handins()
    await fake.remove_student(made.id, users["Celina Wrona"])
    return Class(TestClient(app), fake, made.id, given.id)


async def test_the_overview_reads_the_students_work_and_absences_from_teams(klass):
    view = klass.get("overview")

    assert view["invented"] is False
    students = {s["name"]: s for s in view["students"]}
    assert {n: s["former"] for n, s in students.items()} == {
        "Ala Kowalska": False,
        "Bartek Nowicki": False,
        "Celina Wrona": True,
    }
    assert (students["Ala Kowalska"]["absent"], students["Bartek Nowicki"]["absent"]) == (0, 1)
    (row,) = view["assignments"]
    assert (row["id"], row["title"], row["state"]) == (klass.assignment_id, "Równania", "open")
    assert (row["handed_in"], row["total"], row["average"]) == (1, 3, None)


async def test_the_student_report_is_the_students_own_from_teams(klass):
    bartek = klass.student("Bartek Nowicki")

    view = klass.get(f"students/{bartek}/report")

    assert view["invented"] is False
    assert (view["name"], view["former"]) == ("Bartek Nowicki", False)
    assert view["attendance"] == {"lessons": 1, "absent": 1, "percent": 0}
    (row,) = view["assignments"]
    assert (row["title"], row["submission_state"]) == ("Równania", "handed_in")


async def test_a_note_is_kept_for_a_student_of_the_teachers_own_class(klass):
    ala = klass.student("Ala Kowalska")

    saved = klass.web.put(f"/api/classes/{klass.id}/students/{ala}/note", json={"text": "pilna"})

    assert saved.status_code == 204
    assert klass.get(f"students/{ala}/report")["note"] == "pilna"


async def test_the_assignment_page_has_each_recipient_and_the_banks_points(klass):
    view = klass.get(f"assignments/{klass.assignment_id}")

    assert view["invented"] is False
    assert view["points"] == 2
    rows = {r["name"]: r["state"] for r in view["rows"]}
    assert rows == {
        "Ala Kowalska": "not_handed_in",
        "Bartek Nowicki": "handed_in",
        "Celina Wrona": "not_handed_in",
    }
    assert view["counts"]["handed_in"] == 1 and view["counts"]["total"] == 3


async def test_an_unknown_student_or_assignment_of_an_own_class_is_not_found(klass):
    assert klass.web.get(f"/api/classes/{klass.id}/students/nobody/report").status_code == 404
    assert klass.web.get(f"/api/classes/{klass.id}/assignments/nothing").status_code == 404
