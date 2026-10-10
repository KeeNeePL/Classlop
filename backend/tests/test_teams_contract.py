"""One contract suite for the `teams` interface, run against the real area over FakeGraph (with
Postgres from compose) and against FakeTeams, so the two cannot drift."""

import asyncio
import os
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fake_graph import FakeGraph
from sqlalchemy import delete

from classlop import teams
from classlop.shared import jobs, queue, schedule
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.models import Job, Schedule
from classlop.shared.settings import get_settings
from classlop.teams import handlers
from classlop.teams.fake import FakeTeams
from classlop.teams.graph import GraphClient
from classlop.teams.models import ClassRecord, SettingRecord
from classlop.teams.service import GraphTeams

TEACHER = "teacher-oid"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)


@pytest.fixture(scope="module", autouse=True)
async def stack():
    try:
        await asyncio.to_thread(migrate)
        await asyncio.to_thread(queue.url)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres elasticmq")


@pytest.fixture(autouse=True)
async def teacher(monkeypatch):
    monkeypatch.setattr(get_settings(), "m365_teacher_oid", TEACHER)
    async with sessions().begin() as session:
        await session.execute(delete(ClassRecord))
        await session.execute(delete(SettingRecord))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture(params=["graph", "fake"])
def tenant(request, clock):
    """The area under test, which is also where the test seeds its invented tenant."""
    if request.param == "fake":
        return FakeTeams(clock=clock)
    graph = FakeGraph(TEACHER)
    client = GraphClient(token=lambda: _token(), transport=graph.transport)
    area = GraphTeams(client, clock=clock, records=client)
    return Tenant(area, graph)


async def _token() -> str:
    return "token"


class Tenant:
    """The real area plus the fake Microsoft behind it."""

    def __init__(self, area: GraphTeams, graph: FakeGraph):
        self.area, self.graph = area, graph
        self.add_team, self.add_member = graph.add_team, graph.add_member
        self.remove_member, self.make_owner = graph.remove_member, graph.make_owner
        self.event_of, self.attend = graph.event_of, graph.attend

    def __getattr__(self, name):
        return getattr(self.area, name)


async def test_lists_only_the_teams_the_teacher_owns(tenant):
    mine = tenant.add_team("2A matematyka")
    tenant.add_team("Rada rodziców", owner="someone-else")

    owned = await tenant.list_owned_teams()

    assert [(t.id, t.name) for t in owned] == [(mine, "2A matematyka")]


async def test_listing_follows_paging(tenant):
    ids = {tenant.add_team(f"Klasa {n}") for n in range(5)}

    assert {t.id for t in await tenant.list_owned_teams()} == ids


async def test_linking_a_team_creates_a_class_with_its_general_channel(tenant):
    team = tenant.add_team("2A matematyka")

    linked = await tenant.link_team(team)

    assert linked.name == "2A matematyka"
    assert linked.team_id == team
    assert linked.general_channel_id
    assert await tenant.get_class(linked.id) == linked
    assert linked in await tenant.list_classes()


async def test_a_team_links_once(tenant):
    team = tenant.add_team("2A matematyka")
    await tenant.link_team(team)

    with pytest.raises(teams.AlreadyLinked):
        await tenant.link_team(team)


async def test_a_team_the_teacher_does_not_own_cannot_be_linked(tenant):
    team = tenant.add_team("Rada rodziców", owner="someone-else")

    with pytest.raises(teams.NotOwner):
        await tenant.link_team(team)


async def test_members_who_are_not_owners_become_students(tenant):
    team = tenant.add_team("2A matematyka")
    tenant.add_member(team, "Jan Kowalski")
    tenant.add_member(team, "Ewa Zielinska")
    tenant.add_member(team, "Piotr Wisniewski")

    linked = await tenant.link_team(team)

    students = await tenant.list_students(linked.id)
    assert sorted(s.display_name for s in students) == [
        "Ewa Zielinska",
        "Jan Kowalski",
        "Piotr Wisniewski",
    ]
    assert {s.upn for s in students if s.display_name == "Jan Kowalski"} == {
        "jan.kowalski@example.org"
    }
    assert all(s.former_since is None for s in students)


async def test_an_owner_is_never_a_student(tenant):
    team = tenant.add_team("2A matematyka")
    tenant.add_member(team, "Marta Lis", owner=True)
    pupil = tenant.add_member(team, "Jan Kowalski")
    linked = await tenant.link_team(team)

    tenant.make_owner(team, pupil)
    await tenant.sync_roster(linked.id)

    assert [
        s.display_name for s in await tenant.list_students(linked.id) if not s.former_since
    ] == []


async def test_sync_picks_up_members_who_join_later(tenant):
    team = tenant.add_team("2A matematyka")
    linked = await tenant.link_team(team)

    tenant.add_member(team, "Jan Kowalski")
    await tenant.sync_roster(linked.id)

    assert [s.display_name for s in await tenant.list_students(linked.id)] == ["Jan Kowalski"]


async def test_a_member_who_leaves_becomes_a_former_student_and_keeps_their_record(tenant, clock):
    team = tenant.add_team("2A matematyka")
    leaver = tenant.add_member(team, "Jan Kowalski")
    tenant.add_member(team, "Ewa Zielinska")
    linked = await tenant.link_team(team)
    before = {s.display_name: s.id for s in await tenant.list_students(linked.id)}

    clock.advance(days=3)
    tenant.remove_member(team, leaver)
    await tenant.sync_roster(linked.id)

    after = {s.display_name: s for s in await tenant.list_students(linked.id)}
    assert after["Jan Kowalski"].former_since == clock.now
    assert after["Jan Kowalski"].id == before["Jan Kowalski"]
    assert after["Ewa Zielinska"].former_since is None


async def test_a_former_student_who_rejoins_is_a_student_again(tenant, clock):
    team = tenant.add_team("2A matematyka")
    pupil = tenant.add_member(team, "Jan Kowalski")
    linked = await tenant.link_team(team)
    original = (await tenant.list_students(linked.id))[0].id
    tenant.remove_member(team, pupil)
    await tenant.sync_roster(linked.id)

    tenant.add_member(team, "Jan Kowalski", user_id=pupil)
    await tenant.sync_roster(linked.id)

    [student] = await tenant.list_students(linked.id)
    assert (student.id, student.former_since) == (original, None)


WARSAW = ZoneInfo("Europe/Warsaw")
YEAR_END = date(2026, 9, 30)
MONDAY_8 = teams.Slot(weekday=0, start=time(8, 0), end=time(8, 45))
WEDNESDAY_9 = teams.Slot(weekday=2, start=time(9, 0), end=time(9, 45))


async def _class_with_jan(tenant):
    team = tenant.add_team("2A matematyka")
    tenant.add_member(team, "Jan Kowalski")
    return team, await tenant.link_team(team)


async def test_each_timetable_slot_becomes_a_series_of_lessons_up_to_the_year_end(tenant):
    _, linked = await _class_with_jan(tenant)

    await tenant.add_timetable(linked.id, [MONDAY_8, WEDNESDAY_9], YEAR_END)

    lessons = await tenant.list_lessons(linked.id)
    assert len(lessons) == 9
    assert [(x.start.weekday(), x.start.hour) for x in lessons[:3]] == [(2, 9), (0, 8), (2, 9)]
    assert lessons[0].start == datetime(2026, 9, 2, 9, 0, tzinfo=WARSAW)
    assert lessons[0].end == datetime(2026, 9, 2, 9, 45, tzinfo=WARSAW)
    assert lessons[-1].start.date() == date(2026, 9, 30)
    assert all(x.topic is None and x.join_url for x in lessons)
    assert len({x.join_url for x in lessons}) == 2
    assert (await tenant.get_class(linked.id)).school_year_end == YEAR_END


async def test_a_class_gets_one_timetable(tenant):
    _, linked = await _class_with_jan(tenant)
    await tenant.add_timetable(linked.id, [MONDAY_8], YEAR_END)

    with pytest.raises(teams.TimetableExists):
        await tenant.add_timetable(linked.id, [WEDNESDAY_9], YEAR_END)


async def test_lessons_are_per_class(tenant):
    _, first = await _class_with_jan(tenant)
    other = await tenant.link_team(tenant.add_team("3B matematyka"))
    await tenant.add_timetable(first.id, [MONDAY_8], YEAR_END)

    assert await tenant.list_lessons(other.id) == []


async def test_a_series_invites_the_students_and_follows_the_roster(tenant, clock):
    team, linked = await _class_with_jan(tenant)
    leaver = tenant.add_member(team, "Adam Lis")
    await tenant.sync_roster(linked.id)
    await tenant.add_timetable(linked.id, [MONDAY_8, WEDNESDAY_9], YEAR_END)
    lessons = await tenant.list_lessons(linked.id)
    assert tenant.event_of(lessons[0].id)[1] == {"jan.kowalski@example.org", "adam.lis@example.org"}

    tenant.add_member(team, "Ewa Zielinska")
    tenant.remove_member(team, leaver)
    await tenant.sync_roster(linked.id)

    for lesson in lessons:
        assert tenant.event_of(lesson.id)[1] == {
            "jan.kowalski@example.org",
            "ewa.zielinska@example.org",
        }


async def test_a_single_lesson_needs_a_topic_and_is_one_event(tenant):
    _, linked = await _class_with_jan(tenant)
    start = datetime(2026, 9, 12, 10, 0, tzinfo=WARSAW)
    end = start + timedelta(minutes=45)

    with pytest.raises(ValueError):
        await tenant.add_lesson(linked.id, start, end, "  ")
    assert await tenant.list_lessons(linked.id) == []

    lesson = await tenant.add_lesson(linked.id, start, end, "Funkcje liniowe")

    assert await tenant.list_lessons(linked.id) == [lesson]
    assert (lesson.topic, lesson.start, lesson.end) == ("Funkcje liniowe", start, end)
    assert lesson.join_url
    assert tenant.event_of(lesson.id) == (
        "2A matematyka: Funkcje liniowe",
        {"jan.kowalski@example.org"},
    )


async def test_a_single_lesson_follows_the_roster_too(tenant):
    team, linked = await _class_with_jan(tenant)
    start = datetime(2026, 9, 12, 10, 0, tzinfo=WARSAW)
    lesson = await tenant.add_lesson(linked.id, start, start + timedelta(minutes=45), "Wzory")

    tenant.add_member(team, "Ewa Zielinska")
    await tenant.sync_roster(linked.id)

    assert len(tenant.event_of(lesson.id)[1]) == 2


async def test_roster_sync_is_a_job_that_runs_every_15_minutes(tenant, monkeypatch):
    team = tenant.add_team("2A matematyka")
    linked = await tenant.link_team(team)
    tenant.add_member(team, "Jan Kowalski")
    monkeypatch.setattr(teams, "backend", lambda: tenant)

    await handlers.sync_rosters(Job(kind="teams.sync_rosters", payload={}), _ignore)

    assert [s.display_name for s in await tenant.list_students(linked.id)] == ["Jan Kowalski"]
    await schedule.sync_declared()
    async with sessions()() as session:
        row = await session.get(Schedule, "teams.sync-rosters")
    assert (row.kind, row.every_seconds) == ("teams.sync_rosters", 15 * 60)


async def _ignore(_):
    pass


LESSON_START = datetime(2026, 9, 12, 10, 0, tzinfo=WARSAW)
DAY = 24 * 60


def _at(minute: int) -> datetime:
    return LESSON_START + timedelta(minutes=minute)


async def _lesson(tenant, linked):
    return await tenant.add_lesson(linked.id, LESSON_START, _at(45), "Funkcje liniowe")


async def _held(tenant, names=("Jan Kowalski", "Ewa Zielinska", "Adam Lis")):
    team = tenant.add_team("2A matematyka")
    ids = {n: tenant.add_member(team, n) for n in names}
    linked = await tenant.link_team(team)
    students = {s.display_name: s for s in await tenant.list_students(linked.id)}
    return linked, ids, students, await _lesson(tenant, linked)


def _states(attendance, students):
    by_id = {e.student_id: e for e in attendance.entries}
    return {n: (by_id[s.id].state, by_id[s.id].minutes) for n, s in students.items()}


async def test_attendance_shows_present_late_and_absent_with_minutes(tenant):
    linked, ids, students, lesson = await _held(tenant)
    before = await tenant.get_attendance(linked.id, lesson.id)
    assert before.fetched_at is None
    assert all(e.state is None for e in before.entries)
    tenant.attend(
        lesson.join_url,
        [
            (TEACHER, "Anna Nowak", _at(-2), _at(45)),
            (ids["Jan Kowalski"], "Jan Kowalski", _at(2), _at(10)),
            (ids["Ewa Zielinska"], "Ewa Zielinska", _at(7), _at(30)),
        ],
    )

    got = await tenant.refresh_attendance(linked.id, lesson.id)

    assert _states(got, students) == {
        "Jan Kowalski": ("present", 8),
        "Ewa Zielinska": ("late", 23),
        "Adam Lis": ("absent", 0),
    }
    assert got.unmatched == []
    assert not any(e.overridden for e in got.entries)
    assert await tenant.get_attendance(linked.id, lesson.id) == got


async def test_a_first_join_exactly_at_the_threshold_is_not_late(tenant):
    linked, ids, students, lesson = await _held(tenant, ("Jan Kowalski",))
    tenant.attend(lesson.join_url, [(ids["Jan Kowalski"], "Jan Kowalski", _at(5), _at(40))])

    got = await tenant.refresh_attendance(linked.id, lesson.id)

    assert _states(got, students) == {"Jan Kowalski": ("present", 35)}


async def test_the_lateness_threshold_is_one_setting_defaulting_to_five_minutes(tenant):
    linked, ids, students, lesson = await _held(tenant, ("Ewa Zielinska",))
    tenant.attend(lesson.join_url, [(ids["Ewa Zielinska"], "Ewa Zielinska", _at(7), _at(45))])
    assert await tenant.lateness_threshold() == timedelta(minutes=5)
    assert _states(await tenant.refresh_attendance(linked.id, lesson.id), students) == {
        "Ewa Zielinska": ("late", 38)
    }

    await tenant.set_lateness_threshold(timedelta(minutes=10))

    assert await tenant.lateness_threshold() == timedelta(minutes=10)
    assert _states(await tenant.get_attendance(linked.id, lesson.id), students) == {
        "Ewa Zielinska": ("present", 38)
    }


async def test_every_record_of_the_meeting_is_merged_and_rejoins_count_once(tenant):
    linked, ids, students, lesson = await _held(tenant, ("Jan Kowalski",))
    jan = ids["Jan Kowalski"]
    tenant.attend(
        lesson.join_url,
        [(jan, "Jan Kowalski", _at(1), _at(10)), (jan, "Jan Kowalski", _at(8), _at(15))],
    )
    tenant.attend(lesson.join_url, [(jan, "Jan Kowalski", _at(30), _at(40))])

    got = await tenant.refresh_attendance(linked.id, lesson.id)

    assert _states(got, students) == {"Jan Kowalski": ("present", 24)}


async def test_a_series_shares_one_join_link_but_each_lesson_keeps_its_own_records(tenant):
    _, linked = await _class_with_jan(tenant)
    [jan] = await tenant.list_students(linked.id)
    await tenant.add_timetable(linked.id, [MONDAY_8], YEAR_END)
    first, second = (await tenant.list_lessons(linked.id))[:2]
    assert first.join_url == second.join_url
    tenant.attend(
        first.join_url,
        [(jan.user_id, "Jan Kowalski", first.start + timedelta(minutes=1), first.end)],
    )

    one = await tenant.refresh_attendance(linked.id, first.id)
    two = await tenant.refresh_attendance(linked.id, second.id)

    assert [(e.state, e.minutes) for e in one.entries] == [("present", 44)]
    assert [(e.state, e.minutes) for e in two.entries] == [("absent", 0)]


async def test_an_override_is_marked_and_survives_every_later_fetch(tenant):
    linked, ids, students, lesson = await _held(tenant, ("Jan Kowalski",))
    jan = students["Jan Kowalski"]

    await tenant.override_attendance(linked.id, lesson.id, jan.id, "present")
    tenant.attend(lesson.join_url, [(ids["Jan Kowalski"], "Jan Kowalski", _at(20), _at(40))])
    got = await tenant.refresh_attendance(linked.id, lesson.id)

    [entry] = got.entries
    assert (entry.state, entry.overridden, entry.minutes) == ("present", True, 20)

    await tenant.override_attendance(linked.id, lesson.id, jan.id, None)

    [entry] = (await tenant.get_attendance(linked.id, lesson.id)).entries
    assert (entry.state, entry.overridden) == ("late", False)


async def test_attendees_not_linked_to_a_student_are_unmatched_and_a_link_is_remembered(tenant):
    linked, _, students, lesson = await _held(tenant, ("Jan Kowalski",))
    later = await tenant.add_lesson(linked.id, _at(DAY), _at(DAY + 45), "Wzory")
    tenant.attend(
        lesson.join_url,
        [("stranger-oid", "Telefon Janka", _at(1), _at(41)), (None, "Ola", _at(2), _at(32))],
    )
    tenant.attend(later.join_url, [("stranger-oid", "Telefon Janka", _at(DAY + 1), _at(DAY + 21))])
    jan = students["Jan Kowalski"]

    got = await tenant.refresh_attendance(linked.id, lesson.id)

    assert sorted((u.display_name, u.minutes) for u in got.unmatched) == [
        ("Ola", 30),
        ("Telefon Janka", 40),
    ]
    assert _states(got, students) == {"Jan Kowalski": ("absent", 0)}

    phone = next(u for u in got.unmatched if u.display_name == "Telefon Janka")
    await tenant.link_attendee(linked.id, phone.key, jan.id)

    now = await tenant.get_attendance(linked.id, lesson.id)
    assert _states(now, students) == {"Jan Kowalski": ("present", 40)}
    assert [u.display_name for u in now.unmatched] == ["Ola"]
    ahead = await tenant.refresh_attendance(linked.id, later.id)
    assert _states(ahead, students) == {"Jan Kowalski": ("present", 20)}
    assert ahead.unmatched == []


async def test_a_guest_is_linked_by_display_name_within_the_class(tenant):
    linked, _, students, lesson = await _held(tenant, ("Jan Kowalski",))
    other = await tenant.link_team(tenant.add_team("3B matematyka"))
    other_lesson = await _lesson(tenant, other)
    later = await tenant.add_lesson(linked.id, _at(2 * DAY), _at(2 * DAY + 45), "Wzory")
    tenant.attend(lesson.join_url, [(None, "Ola", _at(1), _at(41))])
    tenant.attend(later.join_url, [(None, "Ola", _at(2 * DAY + 3), _at(2 * DAY + 20))])
    tenant.attend(other_lesson.join_url, [(None, "Ola", _at(1), _at(41))])
    [guest] = (await tenant.refresh_attendance(linked.id, lesson.id)).unmatched

    await tenant.link_attendee(linked.id, guest.key, students["Jan Kowalski"].id)

    assert _states(await tenant.refresh_attendance(linked.id, later.id), students) == {
        "Jan Kowalski": ("present", 17)
    }
    assert len((await tenant.refresh_attendance(other.id, other_lesson.id)).unmatched) == 1


async def test_attendance_is_fetched_at_the_end_plus_45_minutes_and_again_at_2_hours(tenant, clock):
    linked, ids, students, lesson = await _held(tenant, ("Jan Kowalski",))
    jan = ids["Jan Kowalski"]
    tenant.attend(lesson.join_url, [(jan, "Jan Kowalski", _at(1), _at(20))])

    clock.now = lesson.end + timedelta(minutes=44)
    assert await tenant.fetch_due_attendance() == 0
    assert (await tenant.get_attendance(linked.id, lesson.id)).fetched_at is None

    clock.now = lesson.end + timedelta(minutes=45)
    assert await tenant.fetch_due_attendance() == 1
    assert _states(await tenant.get_attendance(linked.id, lesson.id), students) == {
        "Jan Kowalski": ("present", 19)
    }
    assert await tenant.fetch_due_attendance() == 0

    tenant.attend(lesson.join_url, [(jan, "Jan Kowalski", _at(30), _at(40))])
    clock.now = lesson.end + timedelta(hours=2)
    assert await tenant.fetch_due_attendance() == 1
    assert _states(await tenant.get_attendance(linked.id, lesson.id), students) == {
        "Jan Kowalski": ("present", 29)
    }
    clock.now = lesson.end + timedelta(days=1)
    assert await tenant.fetch_due_attendance() == 0


async def test_the_attendance_fetch_is_a_job_that_runs_every_five_minutes(
    tenant, clock, monkeypatch
):
    linked, ids, students, lesson = await _held(tenant, ("Jan Kowalski",))
    tenant.attend(lesson.join_url, [(ids["Jan Kowalski"], "Jan Kowalski", _at(1), _at(40))])
    clock.now = lesson.end + timedelta(hours=1)
    monkeypatch.setattr(teams, "backend", lambda: tenant)

    await handlers.fetch_attendance(Job(kind="teams.fetch_attendance", payload={}), _ignore)

    assert _states(await tenant.get_attendance(linked.id, lesson.id), students) == {
        "Jan Kowalski": ("present", 39)
    }
    await schedule.sync_declared()
    async with sessions()() as session:
        row = await session.get(Schedule, "teams.fetch-attendance")
    assert (row.kind, row.every_seconds) == ("teams.fetch_attendance", 5 * 60)


async def test_a_lapsed_sign_in_raises_what_parks_a_job(monkeypatch):
    async def lapsed(scopes):
        raise jobs.SignInRequired

    monkeypatch.setattr("classlop.teams.graph.graph_token", lapsed)
    monkeypatch.setattr(teams, "_backend", GraphTeams(GraphClient()))
    with pytest.raises(jobs.SignInRequired):
        await teams.list_owned_teams()


async def test_the_fake_backend_serves_the_interface(monkeypatch):
    monkeypatch.setattr(get_settings(), "teams_backend", "fake")
    monkeypatch.setattr(teams, "_backend", None)

    [team, *_] = await teams.list_owned_teams()
    linked = await teams.link_team(team.id)

    assert linked.name == team.name
    assert await teams.list_students(linked.id)
