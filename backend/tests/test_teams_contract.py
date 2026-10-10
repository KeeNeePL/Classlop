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
from classlop.teams.models import ClassRecord
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


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture(params=["graph", "fake"])
def tenant(request, clock):
    """The area under test, which is also where the test seeds its invented tenant."""
    if request.param == "fake":
        return FakeTeams(clock=clock)
    graph = FakeGraph(TEACHER)
    tenant = Tenant(graph)

    async def token() -> str:
        if tenant.lapsed:
            raise jobs.SignInRequired
        return "token"

    tenant.area = GraphTeams(GraphClient(token=token, transport=graph.transport), clock=clock)
    return tenant


class Tenant:
    """The real area plus the fake Microsoft behind it."""

    def __init__(self, graph: FakeGraph):
        self.graph, self.lapsed = graph, False
        self.add_team, self.add_member = graph.add_team, graph.add_member
        self.remove_member, self.make_owner = graph.remove_member, graph.make_owner
        self.event_of = graph.event_of

    def lapse_sign_in(self) -> None:
        self.lapsed = True

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


def _days(lessons):
    return [x.start.day for x in lessons]


async def test_cancelling_a_date_range_cancels_every_occurrence_in_it(tenant):
    _, linked = await _class_with_jan(tenant)
    await tenant.add_timetable(linked.id, [MONDAY_8, WEDNESDAY_9], YEAR_END)
    start = datetime(2026, 9, 15, 10, 0, tzinfo=WARSAW)
    single = await tenant.add_lesson(linked.id, start, start + timedelta(minutes=45), "Wzory")

    await tenant.cancel_lessons(linked.id, date(2026, 9, 14), date(2026, 9, 21))

    lessons = await tenant.list_lessons(linked.id)
    assert len(lessons) == 10
    assert _days([x for x in lessons if x.cancelled]) == [14, 15, 16, 21]
    cancelled_single = next(x for x in lessons if x.id == single.id)
    assert (cancelled_single.cancelled, cancelled_single.topic) == (True, "Wzory")

    await tenant.cancel_lessons(linked.id, date(2026, 9, 14), date(2026, 9, 21))
    assert len([x for x in await tenant.list_lessons(linked.id) if x.cancelled]) == 4


async def test_a_cancelled_lesson_keeps_its_topic(tenant):
    _, linked = await _class_with_jan(tenant)
    await tenant.add_timetable(linked.id, [MONDAY_8], YEAR_END)
    monday = (await tenant.list_lessons(linked.id))[1]
    await tenant.set_lesson_topic(linked.id, monday.id, "Wzory skroconego mnozenia")

    await tenant.cancel_lessons(linked.id, date(2026, 9, 14), date(2026, 9, 14))

    cancelled = (await tenant.list_lessons(linked.id))[1]
    assert (cancelled.cancelled, cancelled.topic) == (True, "Wzory skroconego mnozenia")


async def test_changing_a_slot_ends_the_old_series_and_starts_a_new_one(tenant):
    team, linked = await _class_with_jan(tenant)
    await tenant.add_timetable(linked.id, [MONDAY_8], YEAR_END)
    past = (await tenant.list_lessons(linked.id))[0]
    await tenant.set_lesson_topic(linked.id, past.id, "Potegi")
    tuesday = teams.Slot(weekday=1, start=time(10, 0), end=time(10, 45))

    await tenant.change_slot(linked.id, MONDAY_8, tuesday, date(2026, 9, 21))

    lessons = await tenant.list_lessons(linked.id)
    assert [(x.start.weekday(), x.start.day) for x in lessons] == [
        (0, 7),
        (0, 14),
        (1, 22),
        (1, 29),
    ]
    assert lessons[0].topic == "Potegi"
    assert lessons[2].start == datetime(2026, 9, 22, 10, 0, tzinfo=WARSAW)
    assert lessons[2].join_url != lessons[0].join_url
    assert tenant.event_of(lessons[2].id) == ("2A matematyka", {"jan.kowalski@example.org"})

    tenant.add_member(team, "Ewa Zielinska")
    await tenant.sync_roster(linked.id)
    assert len(tenant.event_of(lessons[2].id)[1]) == 2


async def test_a_slot_changes_only_from_after_its_first_lesson(tenant):
    _, linked = await _class_with_jan(tenant)
    await tenant.add_timetable(linked.id, [MONDAY_8], YEAR_END)

    with pytest.raises(ValueError):
        await tenant.change_slot(linked.id, MONDAY_8, WEDNESDAY_9, date(2026, 9, 7))
    with pytest.raises(LookupError):
        await tenant.change_slot(linked.id, WEDNESDAY_9, MONDAY_8, date(2026, 9, 21))
    assert len(await tenant.list_lessons(linked.id)) == 4


async def test_a_slot_can_change_twice(tenant):
    _, linked = await _class_with_jan(tenant)
    await tenant.add_timetable(linked.id, [MONDAY_8], YEAR_END)
    await tenant.change_slot(linked.id, MONDAY_8, WEDNESDAY_9, date(2026, 9, 14))
    await tenant.change_slot(linked.id, WEDNESDAY_9, MONDAY_8, date(2026, 9, 24))

    assert _days(await tenant.list_lessons(linked.id)) == [7, 16, 23, 28]


async def test_a_lesson_topic_goes_into_the_occurrence_title(tenant):
    _, linked = await _class_with_jan(tenant)
    await tenant.add_timetable(linked.id, [MONDAY_8], YEAR_END)
    first, second = (await tenant.list_lessons(linked.id))[:2]

    set_topic = await tenant.set_lesson_topic(linked.id, first.id, "Funkcje liniowe")

    assert set_topic.topic == "Funkcje liniowe"
    assert tenant.event_of(first.id)[0] == "2A matematyka: Funkcje liniowe"
    assert tenant.event_of(second.id)[0] == "2A matematyka"
    lessons = await tenant.list_lessons(linked.id)
    assert [x.topic for x in lessons[:2]] == ["Funkcje liniowe", None]

    await tenant.set_lesson_topic(linked.id, first.id, " Funkcje kwadratowe ")
    assert (await tenant.list_lessons(linked.id))[0].topic == "Funkcje kwadratowe"
    assert tenant.event_of(first.id)[0] == "2A matematyka: Funkcje kwadratowe"


async def test_a_topic_cannot_be_cleared_to_empty(tenant):
    _, linked = await _class_with_jan(tenant)
    start = datetime(2026, 9, 12, 10, 0, tzinfo=WARSAW)
    single = await tenant.add_lesson(linked.id, start, start + timedelta(minutes=45), "Wzory")
    await tenant.add_timetable(linked.id, [MONDAY_8], YEAR_END)
    occurrence = (await tenant.list_lessons(linked.id))[0]
    await tenant.set_lesson_topic(linked.id, occurrence.id, "Potegi")

    for lesson in (single, occurrence):
        with pytest.raises(ValueError):
            await tenant.set_lesson_topic(linked.id, lesson.id, "  ")

    assert tenant.event_of(single.id)[0] == "2A matematyka: Wzory"
    assert tenant.event_of(occurrence.id)[0] == "2A matematyka: Potegi"
    assert {x.topic for x in await tenant.list_lessons(linked.id)} >= {"Wzory", "Potegi"}


async def test_a_single_lessons_topic_can_change(tenant):
    _, linked = await _class_with_jan(tenant)
    start = datetime(2026, 9, 12, 10, 0, tzinfo=WARSAW)
    single = await tenant.add_lesson(linked.id, start, start + timedelta(minutes=45), "Wzory")

    await tenant.set_lesson_topic(linked.id, single.id, "Ulamki")

    assert (await tenant.list_lessons(linked.id))[0].topic == "Ulamki"
    assert tenant.event_of(single.id)[0] == "2A matematyka: Ulamki"
    with pytest.raises(LookupError):
        await tenant.set_lesson_topic(linked.id, "no-such-lesson", "Ulamki")


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


async def test_a_lapsed_sign_in_raises_what_parks_a_job(tenant):
    team = tenant.add_team("2A matematyka")
    linked = await tenant.link_team(team)
    tenant.lapse_sign_in()

    for call in (
        tenant.list_owned_teams(),
        tenant.link_team(team),
        tenant.sync_roster(linked.id),
        tenant.add_lesson(
            linked.id,
            datetime(2026, 9, 2, 8, tzinfo=UTC),
            datetime(2026, 9, 2, 8, 45, tzinfo=UTC),
            "Funkcje",
        ),
    ):
        with pytest.raises(jobs.SignInRequired):
            await call


async def test_the_fake_backend_serves_the_interface(monkeypatch):
    monkeypatch.setattr(get_settings(), "teams_backend", "fake")
    monkeypatch.setattr(teams, "_backend", None)

    [team, *_] = await teams.list_owned_teams()
    linked = await teams.link_team(team.id)

    assert linked.name == team.name
    assert await teams.list_students(linked.id)
