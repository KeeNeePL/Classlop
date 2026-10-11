"""The Reports of a Class of the Teacher's own, read from `teams` (FakeTeams) in one call per
Class; the bank is in memory and `grading` gives only the results a test hands it."""

import uuid
from datetime import timedelta

import pytest
from e2e_app import create
from fake_work import Offline, invented_class
from fastapi.testclient import TestClient
from tenant import Clock

from classlop import grading, teams
from classlop.dashboard import bank, classes, grader
from classlop.shared import storage
from classlop.teams.fake import FakeTeams
from classlop.teams.ids import as_uuid

OPEN_MEDIUM_III = uuid.UUID(int=1001)  # 2 points


class CountingTeams(FakeTeams):
    def __init__(self, clock):
        super().__init__(clock=clock)
        self.reads: list[str] = []

    async def read_class(self, class_id: str) -> teams.ClassRead:
        self.reads.append(class_id)
        return await super().read_class(class_id)


class Graded:
    """`grading` with the results it is handed, and no Common mistakes."""

    def __init__(self) -> None:
        self.found: list[grading.Result] = []

    async def results(self, assignment_ids: list[uuid.UUID]) -> list[grading.Result]:
        return self.found

    async def common_mistakes(self, assignment_id: uuid.UUID) -> list[grading.ItemMistakes]:
        return []


def graded(submission: teams.Submission, earned: int) -> grading.Result:
    item = dict(
        item_id=uuid.uuid4(),
        number=1,
        ai_points=earned,
        max_points=2,
        reading="readable",
        drawing=False,
        doubt=False,
        ai_transcription="$x = 1$",
        fixed_transcription=None,
        feedback="Dobrze.",
        edited_feedback=None,
        mistake=None,
        verification_note=None,
        override=None,
        effective_points=earned,
    )
    return grading.Result.model_validate(
        dict(
            submission_id=as_uuid(submission.id),
            handed_in_at=submission.handed_in_at,
            status="graded",
            held_reasons=[],
            spot_check_reasons=[],
            summary="",
            comment="",
            pdf_key=None,
            items=[item],
            approved_at=None,
        )
    )


class Class:
    def __init__(
        self,
        web: TestClient,
        fake: CountingTeams,
        grades: Graded,
        class_id: str,
        assignment_id: str,
    ):
        self.web, self.fake, self.grades = web, fake, grades
        self.id, self.assignment_id = class_id, assignment_id

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
    grades = Graded()
    app.dependency_overrides[grader.backend] = lambda: grades
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
    return Class(TestClient(app), fake, grades, made.id, given.id)


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


async def test_an_own_classs_points_come_from_grading_for_the_current_hand_in(klass):
    (handed_in,) = [
        s for s in await klass.fake.list_submissions(klass.assignment_id) if s.handed_in_at
    ]
    klass.grades.found = [graded(handed_in, earned=1)]

    rows = {r["name"]: r for r in klass.get(f"assignments/{klass.assignment_id}")["rows"]}
    assert (rows["Bartek Nowicki"]["state"], rows["Bartek Nowicki"]["percent"]) == ("graded", 50)
    assert klass.get("overview")["assignments"][0]["average"] == 50

    stale = handed_in.model_copy(
        update={"handed_in_at": handed_in.handed_in_at - timedelta(hours=1)}
    )
    klass.grades.found = [graded(stale, earned=2)]

    rows = {r["name"]: r for r in klass.get(f"assignments/{klass.assignment_id}")["rows"]}
    assert (rows["Bartek Nowicki"]["state"], rows["Bartek Nowicki"]["percent"]) == (
        "handed_in",
        None,
    )


async def test_the_submission_view_of_an_own_class_shows_its_held_items(klass):
    (handed_in,) = [
        s for s in await klass.fake.list_submissions(klass.assignment_id) if s.handed_in_at
    ]
    unreadable = grading.Reason(reason="nieczytelne", items=[1])
    klass.grades.found = [
        graded(handed_in, earned=1).model_copy(update={"held_reasons": [unreadable]})
    ]
    bartek = klass.student("Bartek Nowicki")

    view = klass.get(f"assignments/{klass.assignment_id}/submissions/{bartek}")

    assert (view["name"], view["invented"], view["state"]) == ("Bartek Nowicki", False, "graded")
    assert view["held"] and view["held_reasons"] == [{"reason": "nieczytelne", "items": [1]}]
    assert view["submission_id"] == str(as_uuid(handed_in.id))
    assert [(i["number"], i["points"], i["transcription"]) for i in view["items"]] == [
        (1, 1, "$x = 1$")
    ]
    assert (view["earned"], view["available"]) == (1, 2)


async def test_the_submission_view_links_the_handed_in_photos(klass, monkeypatch):
    monkeypatch.setattr(storage, "presigned_url", lambda key: f"https://files.example/{key}")
    (handed_in,) = [
        s for s in await klass.fake.list_submissions(klass.assignment_id) if s.handed_in_at
    ]
    bartek = klass.student("Bartek Nowicki")

    view = klass.get(f"assignments/{klass.assignment_id}/submissions/{bartek}")

    (key,) = handed_in.files
    assert view["files"] == [{"name": "strona-1.jpg", "url": f"https://files.example/{key}"}]
