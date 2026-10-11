"""The Assignment page endpoints, over HTTP with the Teacher signed in; `teams` is stubbed."""

import csv
import io

import pytest
from e2e_app import create
from fastapi.testclient import TestClient

from classlop import teams
from classlop.dashboard.app import create_app

# Closed, so its figures show; the newest, 2c-4, is still open.
PAGE = "/api/classes/2c/assignments/2c-3"


@pytest.fixture
def web():
    return TestClient(create())


def test_the_page_needs_a_session():
    assert TestClient(create_app()).get(PAGE).status_code == 401


def test_the_page_is_ready_for_the_screen_and_marked_invented(web):
    view = web.get(PAGE).json()

    assert (view["title"], view["class_name"], view["invented"]) == ("Układy równań", "2C", True)
    assert view["figures"] and view["average"] is not None
    assert view["counts"]["total"] == len(view["rows"]) == 8
    flagged = [r["flagged"] for r in view["rows"]]
    assert flagged == sorted(flagged, reverse=True)
    # The invented Common mistakes, in the shape `grading` gives them.
    assert [len(i["mistakes"]) for i in view["items"]] == [3, 0, 1]
    assert view["items"][0]["mistakes"][0]["count"] == 6
    assert not view["deletable"] and not view["changeable"]


def test_an_open_assignment_shows_hand_ins_only(web):
    view = web.get("/api/classes/2c/assignments/2c-4").json()

    assert not view["figures"] and view["changeable"]
    assert all(r["percent"] is None for r in view["rows"])


def test_unknown_classes_and_assignments_are_not_found(web):
    assert web.get("/api/classes/9z/assignments/9z-3").status_code == 404
    assert web.get("/api/classes/2c/assignments/1a-3").status_code == 404


def test_the_csv_downloads_one_row_per_recipient(web):
    response = web.get(f"{PAGE}/csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith("attachment")
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0] == [
        "Uczeń",
        "Punkty",
        "Maks.",
        "Procent",
        "Proponowana ocena",
        "Stan",
        "Spóźniona",
    ]
    assert len(rows) == 9
    states = {r[5] for r in rows[1:]}
    assert "brak pracy" in states
    graded = next(r for r in rows[1:] if r[5] == "ocenione")
    assert graded[2] == "6" and graded[3].endswith("%") and graded[4] in "123456"
    assert graded[6] in ("tak", "nie")


def test_zmien_termin_changes_the_times_through_teams(web, monkeypatch):
    calls = []

    async def change_times(assignment_id, due_at=None, close_at=None):
        calls.append((assignment_id, due_at.isoformat(), close_at.isoformat()))

    monkeypatch.setattr(teams, "change_times", change_times)
    body = {"due_at": "2026-10-20T18:00:00Z", "close_at": "2026-10-21T18:00:00Z"}

    assert web.post("/api/assignments/a1/times", json=body).status_code == 204
    assert calls == [("a1", "2026-10-20T18:00:00+00:00", "2026-10-21T18:00:00+00:00")]


def test_dodaj_uczniow_gives_the_assignment_to_more_students_through_teams(web, monkeypatch):
    calls = []

    async def add_recipients(assignment_id, student_ids):
        calls.append((assignment_id, student_ids))
        return []

    monkeypatch.setattr(teams, "add_recipients", add_recipients)

    response = web.post("/api/assignments/a1/recipients", json={"student_ids": ["s1", "s2"]})
    assert response.status_code == 204
    assert calls == [("a1", ["s1", "s2"])]


def test_usun_prace_deletes_through_teams(web, monkeypatch):
    calls = []

    async def delete_assignment(assignment_id):
        calls.append(assignment_id)

    monkeypatch.setattr(teams, "delete_assignment", delete_assignment)

    assert web.delete("/api/assignments/a1").status_code == 204
    assert calls == ["a1"]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValueError("an Assignment that has been handed in cannot be deleted"), 409),
        (teams.ClassReadOnly(), 409),
        (LookupError("a1"), 404),
    ],
)
def test_what_teams_refuses_comes_back_as_an_http_error(web, monkeypatch, error, status):
    async def delete_assignment(assignment_id):
        raise error

    monkeypatch.setattr(teams, "delete_assignment", delete_assignment)

    assert web.delete("/api/assignments/a1").status_code == status
