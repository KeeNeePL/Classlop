"""The Student report, its Note and the Suggested grade thresholds, over HTTP with the Teacher
signed in and the dashboard's records in memory."""

import pytest
from e2e_app import create
from fastapi.testclient import TestClient

REPORT = "/api/classes/2c/students/2c-0/report"


@pytest.fixture
def web():
    return TestClient(create())


def test_the_report_is_ready_for_the_screen_and_marked_invented(web):
    view = web.get(REPORT).json()

    assert (view["name"], view["class_name"], view["invented"]) == ("Ala K.", "2C", True)
    assert len(view["assignments"]) == 5 and len(view["points"]) == 5
    assert [p["type"] for p in view["progress"]] == ["quiz", "exam", "homework"]
    assert view["attendance"]["lessons"] == 12
    assert view["note"] == ""


def test_the_period_narrows_the_report(web):
    everything = web.get(REPORT).json()
    dues = sorted(a["due"] for a in everything["assignments"])

    view = web.get(REPORT, params={"start": dues[1], "end": dues[3]}).json()

    assert sorted(a["due"] for a in view["assignments"]) == dues[1:4]
    assert view["start"] is not None


def test_a_note_is_saved_and_never_reaches_the_csv(web):
    note = "Rozmowa z rodzicami w listopadzie."
    assert web.put("/api/classes/2c/students/2c-0/note", json={"text": note}).status_code == 204

    assert web.get(REPORT).json()["note"] == note
    assert web.get("/api/classes/2c/students/2c-1/report").json()["note"] == ""
    assert note not in web.get("/api/classes/2c/assignments/2c-2/csv").content.decode("utf-8-sig")


def test_thresholds_change_every_suggested_grade_at_once(web):
    page = "/api/classes/2c/assignments/2c-2"
    before = web.get(page).json()
    graded = [r for r in before["rows"] if r["percent"] is not None]

    response = web.put("/api/settings/thresholds", json={"percents": [1, 2, 3, 4, 5]})

    assert response.status_code == 204
    assert web.get("/api/settings/thresholds").json() == {"percents": [1, 2, 3, 4, 5]}
    after = web.get(page).json()
    assert after["thresholds"] == [1, 2, 3, 4, 5]
    assert all(r["suggested_grade"] == 6 for r in after["rows"] if r["percent"])
    assert {r["suggested_grade"] for r in graded} != {6}
    report = web.get("/api/classes/2c/students/2c-3/report").json()
    assert all(a["suggested_grade"] == 6 for a in report["assignments"] if a["percent"])
    csv = web.get(f"{page}/csv").content.decode("utf-8-sig").splitlines()
    assert all(
        line.split(";")[4] == "6" for line in csv[1:] if line.split(";")[3] not in ("", "0%")
    )


@pytest.mark.parametrize(
    "percents", [[30, 50, 70, 85], [50, 30, 70, 85, 100], [30, 50, 70, 85, 101]]
)
def test_thresholds_that_leave_a_grade_without_a_range_are_refused(web, percents):
    assert web.put("/api/settings/thresholds", json={"percents": percents}).status_code == 422


def test_unknown_students_are_not_found(web):
    assert web.get("/api/classes/2c/students/9z-1/report").status_code == 404
    assert web.get("/api/classes/9z/students/2c-0/report").status_code == 404


def test_a_note_for_an_unknown_student_is_not_found(web):
    assert web.put("/api/classes/2c/students/9z-1/note", json={"text": "x"}).status_code == 404
