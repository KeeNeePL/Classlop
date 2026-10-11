"""The Lekcje tab, the Lesson page with its Attendance, the lateness threshold and the calendar
questions on Do zrobienia, over HTTP with the Teacher signed in and `teams` served by FakeTeams."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from e2e_app import create
from fastapi.testclient import TestClient

from classlop.dashboard.app import create_app


@pytest.fixture
def web():
    return TestClient(create())


def at(minutes: int, day: int = -1) -> datetime:
    base = datetime.now(UTC).replace(second=0, microsecond=0)
    return base + timedelta(days=day, minutes=minutes)


def linked_class(web) -> str:
    team = web.get("/api/teams").json()[0]
    return web.post("/api/classes/link", json={"team_id": team["id"]}).json()["id"]


def add_lesson(web, class_id, topic="Funkcje liniowe", start=None, end=None):
    start = start or at(0)
    body = {"start": start.isoformat(), "end": (end or start + timedelta(minutes=45)).isoformat()}
    return web.post(f"/api/classes/{class_id}/lessons", json={**body, "topic": topic})


def held(web) -> tuple[str, str, dict[str, str]]:
    """A Class and a Lesson it had yesterday, and the user id of each Student by name."""
    class_id = linked_class(web)
    assert add_lesson(web, class_id).status_code == 204
    [lesson] = web.get(f"/api/classes/{class_id}/lessons").json()["lessons"]
    students = {
        s["name"]: s["user_id"]
        for s in web.get(f"/api/classes/{class_id}/settings").json()["students"]
    }
    return class_id, lesson["id"], students


def attend(web, class_id, lesson_id, sessions):
    page = web.get(f"/api/classes/{class_id}/lessons/{lesson_id}").json()
    web.app.state.teams.attend(page["join_url"], sessions)


def rows(web, class_id, lesson_id) -> dict[str, tuple]:
    page = web.get(f"/api/classes/{class_id}/lessons/{lesson_id}").json()
    return {s["name"]: (s["state"], s["minutes"], s["overridden"]) for s in page["students"]}


def test_the_lesson_endpoints_need_a_session():
    web = TestClient(create_app())

    assert web.get("/api/classes/x/lessons").status_code == 401
    assert web.get("/api/classes/x/lessons/y").status_code == 401
    assert web.get("/api/settings/lateness").status_code == 401


def test_a_single_lesson_needs_a_topic_and_is_listed_with_it(web):
    class_id = linked_class(web)

    assert add_lesson(web, class_id, "  ").status_code == 422
    assert add_lesson(web, class_id, "Funkcje liniowe", at(0, 1), at(-5, 1)).status_code == 422
    assert add_lesson(web, class_id, "Funkcje liniowe", at(0, 1)).status_code == 204

    [lesson] = web.get(f"/api/classes/{class_id}/lessons").json()["lessons"]
    assert (lesson["topic"], lesson["missing_topic"], lesson["cancelled"]) == (
        "Funkcje liniowe",
        False,
        False,
    )


def test_a_lesson_with_no_topic_is_flagged_only_once_it_has_started(web):
    class_id = linked_class(web)
    roster = upns(web, class_id)
    web.app.state.teams.add_meeting("Konsultacje", at(-30, 0), at(15, 0), attendees=roster)
    web.app.state.teams.add_meeting("Powtorka", at(60, 0), at(105, 0), attendees=roster)

    flags = {
        lesson["start"]: lesson["missing_topic"]
        for lesson in web.get(f"/api/classes/{class_id}/lessons").json()["lessons"]
    }

    assert sorted(flags.values()) == [False, True]
    assert flags[min(flags)] is True


def test_the_teacher_fills_in_a_missing_topic_but_cannot_clear_it(web):
    class_id, lesson_id, _ = held(web)

    assert (
        web.put(
            f"/api/classes/{class_id}/lessons/{lesson_id}/topic", json={"topic": "Ciagi"}
        ).status_code
        == 204
    )
    assert web.get(f"/api/classes/{class_id}/lessons/{lesson_id}").json()["topic"] == "Ciagi"
    assert (
        web.put(
            f"/api/classes/{class_id}/lessons/{lesson_id}/topic", json={"topic": " "}
        ).status_code
        == 422
    )


def test_a_lesson_not_in_the_class_is_not_found(web):
    class_id, _, _ = held(web)

    assert web.get(f"/api/classes/{class_id}/lessons/nope").status_code == 404


def test_attendance_is_unknown_until_the_first_fetch_then_shows_each_state_with_minutes(web):
    class_id, lesson_id, users = held(web)
    start = at(0)
    before = rows(web, class_id, lesson_id)
    assert {state for state, _, _ in before.values()} == {None}

    attend(
        web,
        class_id,
        lesson_id,
        [
            (
                users["Jan Kowalski"],
                "Jan Kowalski",
                start + timedelta(minutes=2),
                start + timedelta(minutes=10),
            ),
            (
                users["Ewa Zielinska"],
                "Ewa Zielinska",
                start + timedelta(minutes=7),
                start + timedelta(minutes=30),
            ),
        ],
    )
    assert web.post(f"/api/classes/{class_id}/lessons/{lesson_id}/refresh").status_code == 204

    assert rows(web, class_id, lesson_id) == {
        "Ewa Zielinska": ("late", 23, False),
        "Jan Kowalski": ("present", 8, False),
        "Piotr Wisniewski": ("absent", 0, False),
    }


def test_an_override_is_marked_and_survives_a_refresh(web):
    class_id, lesson_id, users = held(web)
    jan = next(
        s["id"]
        for s in web.get(f"/api/classes/{class_id}/settings").json()["students"]
        if s["name"] == "Jan Kowalski"
    )
    web.post(f"/api/classes/{class_id}/lessons/{lesson_id}/refresh")

    url = f"/api/classes/{class_id}/lessons/{lesson_id}/attendance/{jan}"
    assert web.put(url, json={"state": "present"}).status_code == 204
    web.post(f"/api/classes/{class_id}/lessons/{lesson_id}/refresh")

    assert rows(web, class_id, lesson_id)["Jan Kowalski"] == ("present", 0, True)

    assert web.put(url, json={"state": None}).status_code == 204
    assert rows(web, class_id, lesson_id)["Jan Kowalski"] == ("absent", 0, False)
    assert web.put(url, json={"state": "sleepy"}).status_code == 422


def test_an_unmatched_attendee_is_linked_to_a_student_for_this_and_later_lessons(web):
    class_id, lesson_id, _ = held(web)
    start = at(0)
    attend(
        web,
        class_id,
        lesson_id,
        [(None, "Piotrek W.", start + timedelta(minutes=1), start + timedelta(minutes=41))],
    )
    web.post(f"/api/classes/{class_id}/lessons/{lesson_id}/refresh")
    page = web.get(f"/api/classes/{class_id}/lessons/{lesson_id}").json()
    assert [(u["name"], u["minutes"]) for u in page["unmatched"]] == [("Piotrek W.", 40)]
    assert rows(web, class_id, lesson_id)["Piotr Wisniewski"][0] == "absent"
    piotr = next(s["id"] for s in page["students"] if s["name"] == "Piotr Wisniewski")

    linked = web.post(
        f"/api/classes/{class_id}/lessons/{lesson_id}/attendees",
        json={"key": page["unmatched"][0]["key"], "student_id": piotr},
    )

    assert linked.status_code == 204
    web.post(f"/api/classes/{class_id}/lessons/{lesson_id}/refresh")
    assert rows(web, class_id, lesson_id)["Piotr Wisniewski"] == ("present", 40, False)
    assert web.get(f"/api/classes/{class_id}/lessons/{lesson_id}").json()["unmatched"] == []


def test_the_lateness_threshold_is_one_setting_for_every_class(web):
    assert web.get("/api/settings/lateness").json() == {"minutes": 5}

    assert web.put("/api/settings/lateness", json={"minutes": 10}).status_code == 204
    assert web.get("/api/settings/lateness").json() == {"minutes": 10}
    assert web.put("/api/settings/lateness", json={"minutes": 0}).status_code == 204
    assert web.put("/api/settings/lateness", json={"minutes": -1}).status_code == 422
    assert web.put("/api/settings/lateness", json={"minutes": 100}).status_code == 422


def test_a_changed_threshold_changes_who_is_late(web):
    class_id, lesson_id, users = held(web)
    start = at(0)
    attend(
        web,
        class_id,
        lesson_id,
        [
            (
                users["Ewa Zielinska"],
                "Ewa Zielinska",
                start + timedelta(minutes=7),
                start + timedelta(minutes=40),
            )
        ],
    )
    web.post(f"/api/classes/{class_id}/lessons/{lesson_id}/refresh")
    assert rows(web, class_id, lesson_id)["Ewa Zielinska"][0] == "late"

    web.put("/api/settings/lateness", json={"minutes": 10})

    assert rows(web, class_id, lesson_id)["Ewa Zielinska"][0] == "present"


def make_class(web, name, *people) -> str:
    found = {
        u["display_name"]: u["user_id"] for u in web.get("/api/users", params={"q": ""}).json()
    }
    body = {"name": name, "student_user_ids": [found[p] for p in people]}
    return web.post("/api/classes", json=body).json()["id"]


def upns(web, class_id) -> list[str]:
    return [s["upn"] for s in web.get(f"/api/classes/{class_id}/settings").json()["students"]]


def sync(web):
    asyncio.run(web.app.state.teams.sync_calendar())


def questions(web) -> list[dict]:
    return [e for e in web.get("/api/home").json()["entries"] if e["kind"] == "calendar_question"]


def test_a_meeting_that_fits_two_classes_asks_which_on_do_zrobienia_and_the_answer_places_it(web):
    first = make_class(web, "4D", "Karolina Mazur", "Jan Kaminski")
    second = make_class(web, "4E", "Karolina Mazur")
    web.app.state.teams.add_meeting(
        "Wycieczka",
        at(60, 2),
        at(105, 2),
        attendees=["karolina.mazur@example.org", "guest@example.org"],
    )
    assert questions(web) == []

    sync(web)

    [ask] = questions(web)
    assert ask["title"] == "Do której klasy należy to spotkanie?"
    assert "Wycieczka" in ask["detail"]
    assert {(c["answer"], c["label"]) for c in ask["choices"]} == {(first, "4D"), (second, "4E")}

    answered = web.post(f"/api/calendar-questions/{ask['question_id']}", json={"answer": first})

    assert answered.status_code == 204
    assert questions(web) == []
    assert len(web.get(f"/api/classes/{first}/lessons").json()["lessons"]) == 1
    assert web.get(f"/api/classes/{second}/lessons").json()["lessons"] == []


def test_a_meeting_of_no_class_asks_to_keep_or_hide_it(web):
    web.app.state.teams.add_meeting(
        "Rada pedagogiczna", at(60, 2), at(105, 2), attendees=["x@example.org"]
    )
    sync(web)

    [ask] = questions(web)

    assert [c["answer"] for c in ask["choices"]] == ["keep", "hide"]
    refused = web.post(f"/api/calendar-questions/{ask['question_id']}", json={"answer": "nope"})
    assert refused.status_code == 409
    hidden = web.post(f"/api/calendar-questions/{ask['question_id']}", json={"answer": "hide"})
    assert hidden.status_code == 204
    assert questions(web) == []
