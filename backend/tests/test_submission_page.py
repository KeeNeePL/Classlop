"""The Submission view and the Teacher's actions, over HTTP with the Teacher signed in, on the
invented data and its stand-in for `grading`."""

import pytest
from e2e_app import create
from fastapi.testclient import TestClient

from classlop.dashboard import invented

# Closed, so changes are open: Damian R. on Zbiory liczbowe in 1A.
PAGE = "/api/classes/1a/assignments/1a-0/submissions/1a-3"
SUMMARY = "/api/classes/1a/assignments/1a-0"


@pytest.fixture
def web():
    invented.GRADING.reset()
    yield TestClient(create())
    invented.GRADING.reset()


def test_a_submission_shows_each_item_with_its_transcription_points_and_feedback(web):
    view = web.get(PAGE).json()

    assert (view["name"], view["assignment_title"], view["invented"]) == (
        "Damian R.",
        "Zbiory liczbowe",
        True,
    )
    assert view["changeable"] and view["status"] == "graded"
    assert [i["number"] for i in view["items"]] == [1, 2, 3]
    first = view["items"][0]
    assert "$" in first["text"] and first["transcription"] and first["feedback"]
    assert first["points"] == first["ai_points"] and first["override"] is None
    assert view["earned"] == sum(i["points"] for i in view["items"])
    assert view["available"] == 6


def item_url(view, number: int, action: str) -> str:
    item = view["items"][number - 1]
    return f"/api/submissions/{view['submission_id']}/items/{item['item_id']}/{action}"


def row(summary, student_id: str):
    return next(r for r in summary["rows"] if r["student_id"] == student_id)


def test_an_override_changes_the_points_here_and_in_the_assignment_summary(web):
    view = web.get(PAGE).json()
    first = view["items"][0]
    points = 0 if first["points"] else 2

    response = web.post(
        item_url(view, 1, "override"),
        json={"handed_in_at": view["handed_in_at"], "points": points},
    )

    assert response.status_code == 204
    after = web.get(PAGE).json()
    assert after["items"][0]["override"] == after["items"][0]["points"] == points
    assert after["items"][0]["ai_points"] == first["ai_points"]
    assert after["earned"] == view["earned"] - first["points"] + points
    assert row(web.get(SUMMARY).json(), "1a-3")["earned"] == after["earned"]


def test_points_beyond_the_item_are_refused(web):
    view = web.get(PAGE).json()

    response = web.post(
        item_url(view, 1, "override"), json={"handed_in_at": view["handed_in_at"], "points": 3}
    )
    assert response.status_code == 409


def test_a_fixed_transcription_regrades_the_item_and_drops_its_override(web):
    view = web.get(PAGE).json()
    hand_in = view["handed_in_at"]
    web.post(item_url(view, 1, "override"), json={"handed_in_at": hand_in, "points": 0})

    response = web.post(
        item_url(view, 1, "transcription"),
        json={"handed_in_at": hand_in, "transcription": "$x = 12$"},
    )

    assert response.status_code == 204
    first = web.get(PAGE).json()["items"][0]
    assert (first["transcription"], first["fixed"], first["override"]) == ("$x = 12$", True, None)


def test_edited_feedback_shows_instead_of_the_ais(web):
    view = web.get(PAGE).json()

    response = web.post(
        item_url(view, 2, "feedback"),
        json={"handed_in_at": view["handed_in_at"], "feedback": "Sprawdź znak w drugim nawiasie."},
    )

    assert response.status_code == 204
    second = web.get(PAGE).json()["items"][1]
    assert (second["feedback"], second["edited"]) == ("Sprawdź znak w drugim nawiasie.", True)


def held_student(web, assignment="1a-1"):
    summary = web.get(f"/api/classes/1a/assignments/{assignment}").json()
    return next(r["student_id"] for r in summary["rows"] if r["held"])


def test_zatwierdz_releases_a_held_submission_into_the_figures(web):
    student = held_student(web)
    url = f"/api/classes/1a/assignments/1a-1/submissions/{student}"
    view = web.get(url).json()
    assert view["held"] and view["held_reasons"]

    response = web.post(
        f"/api/submissions/{view['submission_id']}/approve",
        json={"handed_in_at": view["handed_in_at"]},
    )

    assert response.status_code == 204
    assert not web.get(url).json()["held"]
    released = row(web.get("/api/classes/1a/assignments/1a-1").json(), student)
    assert not released["held"] and released["percent"] is not None


def test_a_failed_grading_is_graded_again(web):
    url = "/api/classes/1a/assignments/1a-0/submissions/1a-5"
    view = web.get(url).json()
    assert (view["status"], view["items"]) == ("failed", [])
    body = {"handed_in_at": view["handed_in_at"]}
    assert (
        web.post(f"/api/submissions/{view['submission_id']}/approve", json=body).status_code == 409
    )

    response = web.post(f"/api/submissions/{view['submission_id']}/grade-again", json=body)

    assert response.status_code == 204
    after = web.get(url).json()
    assert after["status"] == "graded" and len(after["items"]) == 3
    assert row(web.get(SUMMARY).json(), "1a-5")["state"] == "graded"


def test_before_the_due_time_changes_are_refused(web):
    summary = web.get("/api/classes/1a/assignments/1a-4").json()
    student = next(r["student_id"] for r in summary["rows"] if r["state"] == "graded")
    view = web.get(f"/api/classes/1a/assignments/1a-4/submissions/{student}").json()
    assert not view["changeable"]

    response = web.post(
        item_url(view, 1, "override"), json={"handed_in_at": view["handed_in_at"], "points": 0}
    )
    assert response.status_code == 409


def test_previous_and_next_follow_the_assignment_pages_order(web):
    summary = web.get(SUMMARY).json()
    order = [r["student_id"] for r in summary["rows"] if r["state"] != "missing"]
    middle = web.get(f"/api/classes/1a/assignments/1a-0/submissions/{order[1]}").json()

    assert (middle["previous"]["student_id"], middle["next"]["student_id"]) == (order[0], order[2])
    first = web.get(f"/api/classes/1a/assignments/1a-0/submissions/{order[0]}").json()
    assert first["previous"] is None


def test_unknown_submissions_are_not_found(web):
    assert web.get("/api/classes/1a/assignments/1a-0/submissions/9z-1").status_code == 404
    assert web.get("/api/classes/1a/assignments/2c-0/submissions/1a-3").status_code == 404
