"""Creating, linking, managing and deleting a Class, over HTTP with the Teacher signed in and
`teams` served by FakeTeams."""

import pytest
from e2e_app import create
from fastapi.testclient import TestClient

from classlop.dashboard.app import create_app


@pytest.fixture
def web():
    return TestClient(create())


def make_class(web, name="Klasa 4D", *names) -> str:
    """Create a Class from the demo tenant's users named; the first two when none are."""
    found = {
        u["display_name"]: u["user_id"] for u in web.get("/api/users", params={"q": ""}).json()
    }
    picked = [found[n] for n in names] or list(found.values())[:2]
    response = web.post("/api/classes", json={"name": name, "student_user_ids": picked})
    assert response.status_code == 200
    return response.json()["id"]


def settings(web, class_id):
    return web.get(f"/api/classes/{class_id}/settings").json()


def test_the_class_endpoints_need_a_session():
    web = TestClient(create_app())

    assert web.post("/api/classes", json={"name": "4D", "student_user_ids": []}).status_code == 401
    assert web.get("/api/classes/x/settings").status_code == 401
    assert web.delete("/api/classes/x", params={"name": "4D"}).status_code == 401


def test_the_teacher_searches_tenant_users_by_name(web):
    found = web.get("/api/users", params={"q": "kam"}).json()

    assert [u["display_name"] for u in found] == ["Jan Kaminski"]


def test_a_new_class_is_a_team_with_the_picked_students_and_shows_in_the_sidebar(web):
    class_id = make_class(web, "Klasa 4D", "Karolina Mazur", "Jan Kaminski")

    view = settings(web, class_id)
    assert (view["name"], view["state"]) == ("Klasa 4D", "active")
    assert [s["name"] for s in view["students"]] == ["Jan Kaminski", "Karolina Mazur"]
    assert not any(s["former"] for s in view["students"])
    sidebar = web.get("/api/home").json()["classes"]
    assert {"id": class_id, "name": "Klasa 4D", "graded": 0} in sidebar


def test_a_team_the_teacher_owns_is_linked_as_a_class_once(web):
    owned = web.get("/api/teams").json()
    assert [t["name"] for t in owned] == ["Klasa 2A matematyka", "Klasa 3B matematyka"]

    response = web.post("/api/classes/link", json={"team_id": owned[0]["id"]})
    assert response.status_code == 200
    view = settings(web, response.json()["id"])
    assert [s["name"] for s in view["students"]] == [
        "Ewa Zielinska",
        "Jan Kowalski",
        "Piotr Wisniewski",
    ]
    assert [t["name"] for t in web.get("/api/teams").json()] == ["Klasa 3B matematyka"]
    assert web.post("/api/classes/link", json={"team_id": owned[0]["id"]}).status_code == 409


def test_a_team_the_teacher_does_not_own_cannot_be_linked(web):
    assert web.post("/api/classes/link", json={"team_id": "nope"}).status_code == 403


def test_an_added_student_joins_and_a_removed_one_becomes_a_former_student(web):
    class_id = make_class(web, "Klasa 4D", "Karolina Mazur")
    jan = web.get("/api/users", params={"q": "kam"}).json()[0]

    added = web.post(f"/api/classes/{class_id}/students", json={"user_id": jan["user_id"]})
    assert added.status_code == 204
    students = settings(web, class_id)["students"]
    assert [s["name"] for s in students] == ["Jan Kaminski", "Karolina Mazur"]

    karolina = next(s for s in students if s["name"] == "Karolina Mazur")
    assert web.delete(f"/api/classes/{class_id}/students/{karolina['id']}").status_code == 204
    after = {s["name"]: s["former"] for s in settings(web, class_id)["students"]}
    assert after == {"Jan Kaminski": False, "Karolina Mazur": True}


def test_a_student_the_class_does_not_have_is_not_found(web):
    class_id = make_class(web)

    assert web.delete(f"/api/classes/{class_id}/students/nobody").status_code == 404


def test_renaming_a_class_renames_it_in_the_sidebar(web):
    class_id = make_class(web)

    assert web.patch(f"/api/classes/{class_id}", json={"name": "Klasa 4E"}).status_code == 204

    assert settings(web, class_id)["name"] == "Klasa 4E"
    assert "Klasa 4E" in [c["name"] for c in web.get("/api/home").json()["classes"]]


def test_a_blank_name_is_refused(web):
    class_id = make_class(web)

    assert web.patch(f"/api/classes/{class_id}", json={"name": "  "}).status_code == 422
    assert web.post("/api/classes", json={"name": "", "student_user_ids": []}).status_code == 422


def test_deleting_needs_the_name_and_takes_the_notes_with_it(web):
    class_id = make_class(web, "Klasa 4D")
    other = make_class(web, "Klasa 4E")
    notes = web.app.state.notes
    notes.kept = {(class_id, "s1"): "spokojny", (other, "s2"): "pracowity"}

    assert web.delete(f"/api/classes/{class_id}", params={"name": "4D"}).status_code == 409
    assert settings(web, class_id)["name"] == "Klasa 4D"
    assert len(notes.kept) == 2

    assert web.delete(f"/api/classes/{class_id}", params={"name": "Klasa 4D"}).status_code == 204
    assert web.get(f"/api/classes/{class_id}/settings").status_code == 404
    assert notes.kept == {(other, "s2"): "pracowity"}
    assert class_id not in [c["id"] for c in web.get("/api/home").json()["classes"]]


def test_a_class_whose_team_was_deleted_is_read_only_until_restored(web):
    class_id = make_class(web)
    teams = web.app.state.teams
    team_id = teams._classes[class_id].team_id
    teams.delete_team(team_id)

    view = settings(web, class_id)
    assert view["state"] == "team_deleted" and view["team_deleted_at"]
    assert web.patch(f"/api/classes/{class_id}", json={"name": "X"}).status_code == 409
    user = web.get("/api/users", params={"q": "kam"}).json()[0]["user_id"]
    assert web.post(f"/api/classes/{class_id}/students", json={"user_id": user}).status_code == 409

    teams.undelete_team(team_id)
    assert web.post(f"/api/classes/{class_id}/restore-team").status_code == 204
    assert settings(web, class_id)["state"] == "active"


def test_a_class_whose_team_was_deleted_can_still_be_deleted(web):
    class_id = make_class(web, "Klasa 4D")
    teams = web.app.state.teams
    teams.delete_team(teams._classes[class_id].team_id)
    assert settings(web, class_id)["state"] == "team_deleted"

    assert web.delete(f"/api/classes/{class_id}", params={"name": "Klasa 4D"}).status_code == 204
    assert web.get(f"/api/classes/{class_id}/settings").status_code == 404


def test_a_new_class_has_an_overview_with_its_students_and_nothing_invented(web):
    class_id = make_class(web, "Klasa 4D", "Karolina Mazur")

    view = web.get(f"/api/classes/{class_id}/overview").json()

    assert (view["name"], view["invented"]) == ("Klasa 4D", False)
    assert [s["name"] for s in view["students"]] == ["Karolina Mazur"]
    assert view["assignments"] == []


def test_a_class_the_real_area_does_not_know_is_not_found():
    from fastapi import HTTPException
    from sqlalchemy.exc import NoResultFound

    from classlop.dashboard.actions import refusing

    with pytest.raises(HTTPException) as refused, refusing():
        raise NoResultFound

    assert refused.value.status_code == 404


def test_opening_the_settings_releases_a_class_whose_team_is_back(web):
    class_id = make_class(web)
    teams = web.app.state.teams
    team_id = teams._classes[class_id].team_id
    teams.delete_team(team_id)
    assert settings(web, class_id)["state"] == "team_deleted"

    teams.undelete_team(team_id)

    assert settings(web, class_id)["state"] == "active"


def test_a_class_held_for_thirty_days_is_deleted_with_its_notes(web):
    from datetime import UTC, datetime, timedelta

    class_id = make_class(web)
    teams = web.app.state.teams
    teams.delete_team(teams._classes[class_id].team_id)
    assert settings(web, class_id)["state"] == "team_deleted"
    web.app.state.notes.kept = {(class_id, "s1"): "spokojny"}

    teams._clock = lambda: datetime.now(UTC) + timedelta(days=31)

    assert web.get(f"/api/classes/{class_id}/settings").status_code == 404
    assert web.app.state.notes.kept == {}
