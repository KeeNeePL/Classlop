"""The Class overview endpoint, over HTTP with the Teacher signed in."""

from e2e_app import create
from fastapi.testclient import TestClient

from classlop.dashboard.app import create_app


def test_overview_needs_a_session():
    assert TestClient(create_app()).get("/api/classes/2c/overview").status_code == 401


def test_overview_is_ready_for_the_screen_and_marked_invented():
    view = TestClient(create()).get("/api/classes/2c/overview").json()

    assert view["name"] == "2C"
    assert view["invented"] is True
    assert [c["type"] for c in view["progress"]] == ["quiz", "exam", "homework"]
    assert all(c["average"] is not None for c in view["progress"])
    sections = view["progress"][0]["sections"]
    assert [s["name"] for s in sections][:2] == ["Liczby rzeczywiste", "Wyrażenia algebraiczne"]
    assert any(s["percent"] is None for s in sections)
    assert any(s["percent"] is not None for s in sections)
    assert view["assignments"] and view["students"]
    given = [a["given_at"] for a in view["assignments"]]
    assert given == sorted(given, reverse=True)
    assert any(s["former"] for s in view["students"])
    assert 0 < len(view["attention"]) <= 5
    assert all(a["reasons"] for a in view["attention"])


def test_the_sidebars_classes_each_have_an_overview_and_others_are_unknown():
    web = TestClient(create())

    assert [web.get(f"/api/classes/{c}/overview").status_code for c in ("1a", "2c", "3b")] == [
        200
    ] * 3
    assert web.get("/api/classes/9z/overview").status_code == 404
