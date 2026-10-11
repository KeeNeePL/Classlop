"""The Reports and the Submission view over `grading`: what they ask of it, and the real thing on
the compose Postgres. The Classes themselves are still invented, until `teams` is wired (#81)."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from e2e_app import create
from fake_grading import InMemoryGrader
from fastapi.testclient import TestClient
from sqlalchemy import delete

from classlop import grading
from classlop.dashboard import grader, invented
from classlop.grading.models import GradedItem, GradedSubmission
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate

SUMMARY = "/api/classes/1a/assignments/1a-3"


class Counting(InMemoryGrader):
    def __init__(self, drop_results=False, shift=None):
        super().__init__()
        self.drop_results, self.shift = drop_results, shift
        self.mistakes_asked: list[uuid.UUID] = []

    async def results(self, assignment_ids):
        found = await super().results(assignment_ids)
        if self.drop_results:
            return []
        if self.shift:
            return [
                r.model_copy(update={"handed_in_at": r.handed_in_at + self.shift}) for r in found
            ]
        return found

    async def common_mistakes(self, assignment_id):
        self.mistakes_asked.append(assignment_id)
        return await super().common_mistakes(assignment_id)


def web_with(graded) -> TestClient:
    app = create()
    app.dependency_overrides[grader.backend] = lambda: graded
    return TestClient(app)


def states(web: TestClient) -> set[str]:
    return {r["state"] for r in web.get(SUMMARY).json()["rows"]}


def test_a_screen_reads_the_whole_class_from_grading_in_one_call():
    graded = Counting()
    web = web_with(graded)

    web.get("/api/classes/1a/overview")
    assert len(graded.calls) == 1
    # One id per Assignment of the Class.
    assert len(set(graded.calls[0])) == 5

    web.get(SUMMARY)
    assert len(graded.calls) == 2


def test_the_common_mistakes_are_those_of_the_assignment_asked_of_grading():
    graded = Counting()

    view = web_with(graded).get(SUMMARY).json()

    assert graded.mistakes_asked == [invented.assignment_uuid("1a-3")]
    assert [len(i["mistakes"]) for i in view["items"]] == [3, 1]


def test_work_with_no_result_yet_is_still_being_graded():
    web = web_with(Counting(drop_results=True))

    assert "graded" not in states(web) and "handed_in" in states(web)
    view = web.get(SUMMARY).json()
    assert view["average"] is None and view["counts"]["held"] == 0


def test_a_result_of_an_older_hand_in_does_not_count():
    web = web_with(Counting(shift=timedelta(hours=-1)))

    assert "graded" not in states(web)


def test_the_submission_view_shows_nothing_to_act_on_while_grading_is_not_done():
    web = web_with(Counting(drop_results=True))

    view = web.get("/api/classes/1a/assignments/1a-3/submissions/1a-3").json()

    assert (view["status"], view["items"], view["submission_id"]) == (None, [], None)


@pytest.fixture(scope="module")
async def stack():
    try:
        await asyncio.to_thread(migrate)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres")


@pytest.fixture
async def stored(stack):
    """The real `grading`, with nothing stored for the invented Assignments."""

    async def clear() -> None:
        ids = [invented.assignment_uuid(f"1a-{n}") for n in range(5)]
        async with sessions().begin() as session:
            await session.execute(
                delete(GradedSubmission).where(GradedSubmission.assignment_id.in_(ids))
            )

    await clear()
    yield
    await clear()


@pytest.fixture
def real():
    app = create()
    del app.dependency_overrides[grader.backend]
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def store(assignment, student_id: str, points: list[int], held: bool = False) -> datetime:
    """A graded Submission of the invented Class as `grading.grade` would have stored it."""
    mine = next(s for s in assignment.submissions if s.student_id == student_id)
    at, sid = (
        invented.handed_in_at(assignment, mine),
        invented.submission_id(assignment.id, student_id),
    )
    async with sessions().begin() as session:
        session.add(
            GradedSubmission(
                submission_id=sid,
                handed_in_at=at,
                assignment_id=invented.assignment_uuid(assignment.id),
                due_at=assignment.due,
                status="graded",
                held_reasons=[{"reason": "Niepewny odczyt", "items": [2]}] if held else [],
                spot_check_reasons=[],
                comment="",
                items=[
                    GradedItem(
                        submission_id=sid,
                        handed_in_at=at,
                        item_id=invented.item_id(assignment.id, n),
                        position=n,
                        number=n,
                        max_points=i.points,
                        ai_points=p,
                        reading="unsure" if held and n == 2 else "readable",
                        drawing=False,
                        doubt=False,
                        ai_transcription="$x = 5$",
                        feedback="Poprawnie.",
                    )
                    for n, (i, p) in enumerate(zip(assignment.items, points, strict=False), 1)
                ],
            )
        )
    return at


async def worked(web: httpx.AsyncClient) -> tuple[list[str], list]:
    """The Students of 1a-3 who handed in, and its Assignment as the invented data has it."""
    await web.get(SUMMARY)  # pins the invented Assignments' Items
    (assignment,) = [a for a in invented.scenario(datetime.now(UTC)) if a.id == "1a-3"]
    graded = [s.student_id for s in assignment.submissions if s.state == "graded"]
    return graded, assignment


async def row(web: httpx.AsyncClient, student_id: str) -> dict:
    found = (await web.get(SUMMARY)).json()["rows"]
    return next(r for r in found if r["student_id"] == student_id)


async def test_what_grading_stored_is_what_the_assignment_summary_shows(stored, real):
    async with real as web:
        students, assignment = await worked(web)
        assert (await row(web, students[0]))["state"] == "handed_in"

        await store(assignment, students[0], [1, 0])
        await store(assignment, students[1], [1, 1], held=True)

        done, held = await row(web, students[0]), await row(web, students[1])
        assert (done["state"], done["earned"], done["available"]) == (
            "graded",
            1,
            sum(i.points for i in assignment.items),
        )
        # Held until Zatwierdź: no points move any figure.
        assert (held["held"], held["earned"]) == (True, None)


async def test_the_teachers_actions_reach_grading(stored, real):
    async with real as web:
        students, assignment = await worked(web)
        await store(assignment, students[0], [1, 0])
        await store(assignment, students[1], [1, 1], held=True)
        page = f"/api/classes/1a/assignments/1a-3/submissions/{students[0]}"
        view = (await web.get(page)).json()
        first = view["items"][0]

        response = await web.post(
            f"/api/submissions/{view['submission_id']}/items/{first['item_id']}/override",
            json={"handed_in_at": view["handed_in_at"], "points": 0},
        )

        assert response.status_code == 204
        stored_result = await grading.result(
            uuid.UUID(view["submission_id"]), datetime.fromisoformat(view["handed_in_at"])
        )
        assert stored_result is not None and stored_result.items[0].override == 0
        assert (await row(web, students[0]))["earned"] == 0

        held = (await web.get(f"/api/classes/1a/assignments/1a-3/submissions/{students[1]}")).json()
        assert held["held"] and held["held_reasons"][0]["items"] == [2]
        approved = await web.post(
            f"/api/submissions/{held['submission_id']}/approve",
            json={"handed_in_at": held["handed_in_at"]},
        )
        assert approved.status_code == 204
        assert (await row(web, students[1]))["earned"] == 2


async def test_grading_refuses_what_the_teacher_may_not_yet_do(stored, real):
    async with real as web:
        students, assignment = await worked(web)
        await store(assignment, students[0], [1, 0])
        view = (await web.get(f"/api/classes/1a/assignments/1a-3/submissions/{students[0]}")).json()

        response = await web.post(
            f"/api/submissions/{view['submission_id']}/items/{view['items'][0]['item_id']}/override",
            json={"handed_in_at": view["handed_in_at"], "points": 5},
        )

        assert response.status_code == 409
