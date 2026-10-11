"""The Timetable in Ustawienia klasy, over HTTP with the Teacher signed in and `teams` served by
FakeTeams: every change goes through `teams`."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from e2e_app import create
from fastapi.testclient import TestClient
from test_classes_page import make_class

WARSAW = ZoneInfo("Europe/Warsaw")
MONDAY_8 = {"weekday": 0, "start": "08:00:00", "end": "08:45:00"}
THURSDAY_10 = {"weekday": 3, "start": "10:00:00", "end": "10:45:00"}


@pytest.fixture
def web():
    return TestClient(create())


def today() -> date:
    return datetime.now(WARSAW).date()


def year_end() -> date:
    """Four weeks of Lessons, today's included: four of each slot."""
    return today() + timedelta(days=27)


def timetable(web, class_id):
    return web.get(f"/api/classes/{class_id}/timetable").json()


def enter(web, class_id, slots):
    end = year_end().isoformat()
    return web.post(
        f"/api/classes/{class_id}/timetable", json={"slots": slots, "school_year_end": end}
    )


def test_a_class_without_a_timetable_has_no_slots_and_no_lessons(web):
    view = timetable(web, make_class(web))

    assert view == {"school_year_end": None, "slots": [], "lessons": []}


def test_the_timetable_entered_shows_its_slots_and_upcoming_lessons(web):
    class_id = make_class(web)

    assert enter(web, class_id, [THURSDAY_10, MONDAY_8]).status_code == 204

    view = timetable(web, class_id)
    assert view["school_year_end"] == year_end().isoformat()
    assert view["slots"] == [MONDAY_8, THURSDAY_10]
    starts = [datetime.fromisoformat(x["start"]) for x in view["lessons"]]
    assert len(starts) == 8
    assert starts == sorted(starts)
    assert {(s.astimezone(WARSAW).weekday(), s.astimezone(WARSAW).hour) for s in starts} == {
        (0, 8),
        (3, 10),
    }
    assert all(not x["cancelled"] and x["topic"] is None for x in view["lessons"])


def test_the_timetable_is_entered_once(web):
    class_id = make_class(web)
    enter(web, class_id, [MONDAY_8])

    assert enter(web, class_id, [THURSDAY_10]).status_code == 409
    assert timetable(web, class_id)["slots"] == [MONDAY_8]


def test_a_timetable_needs_a_slot_that_ends_after_it_starts(web):
    class_id = make_class(web)
    backwards = {"weekday": 1, "start": "10:00:00", "end": "09:15:00"}
    sunday_after = {"weekday": 7, "start": "10:00:00", "end": "10:45:00"}

    assert enter(web, class_id, []).status_code == 422
    assert enter(web, class_id, [backwards]).status_code == 422
    assert enter(web, class_id, [sunday_after]).status_code == 422
    assert timetable(web, class_id)["slots"] == []


def test_an_unknown_class_has_no_timetable(web):
    assert web.get("/api/classes/nope/timetable").status_code == 404
    assert enter(web, "nope", [MONDAY_8]).status_code == 404


def cancelled(web, class_id) -> list[date]:
    return [
        datetime.fromisoformat(x["start"]).astimezone(WARSAW).date()
        for x in timetable(web, class_id)["lessons"]
        if x["cancelled"]
    ]


def test_a_break_cancels_every_lesson_in_its_dates(web):
    class_id = make_class(web)
    enter(web, class_id, [MONDAY_8, THURSDAY_10])
    first, last = today() + timedelta(days=7), today() + timedelta(days=13)

    response = web.post(
        f"/api/classes/{class_id}/breaks",
        json={"first": first.isoformat(), "last": last.isoformat()},
    )

    assert response.status_code == 204
    days = cancelled(web, class_id)
    assert len(days) == 2
    assert all(first <= d <= last for d in days)
    assert len(timetable(web, class_id)["lessons"]) == 8


def test_a_break_ends_on_or_after_its_first_day(web):
    class_id = make_class(web)
    enter(web, class_id, [MONDAY_8])
    first, last = today() + timedelta(days=7), today() + timedelta(days=6)

    response = web.post(
        f"/api/classes/{class_id}/breaks",
        json={"first": first.isoformat(), "last": last.isoformat()},
    )

    assert response.status_code == 422
    assert cancelled(web, class_id) == []


def change(web, class_id, old, new, from_date):
    return web.post(
        f"/api/classes/{class_id}/timetable/change",
        json={"old": old, "new": new, "from_date": from_date.isoformat()},
    )


def test_a_slot_changed_from_a_date_keeps_the_lessons_before_it(web):
    class_id = make_class(web)
    enter(web, class_id, [MONDAY_8])
    from_date = today() + timedelta(days=14)

    assert change(web, class_id, MONDAY_8, THURSDAY_10, from_date).status_code == 204

    view = timetable(web, class_id)
    assert view["slots"] == [THURSDAY_10]
    lessons = [(datetime.fromisoformat(x["start"]).astimezone(WARSAW), x) for x in view["lessons"]]
    assert all(s.weekday() == 0 for s, _ in lessons if s.date() < from_date)
    assert all(s.weekday() == 3 for s, _ in lessons if s.date() >= from_date)
    assert len([s for s, _ in lessons if s.date() < from_date]) == 2


def test_a_slot_change_needs_a_current_slot_and_a_date_after_its_first_lesson(web):
    class_id = make_class(web)
    enter(web, class_id, [MONDAY_8])

    assert (
        change(web, class_id, THURSDAY_10, MONDAY_8, today() + timedelta(days=14)).status_code
        == 404
    )
    assert change(web, class_id, MONDAY_8, THURSDAY_10, today()).status_code == 409
    assert timetable(web, class_id)["slots"] == [MONDAY_8]
