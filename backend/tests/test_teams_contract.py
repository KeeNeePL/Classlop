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
from classlop.teams.models import CalendarCursor, CalendarSeriesRecord, ClassRecord
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
        for table in (ClassRecord, CalendarSeriesRecord, CalendarCursor):
            await session.execute(delete(table))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture(params=["graph", "fake"])
def tenant(request, clock):
    """The area under test, which is also where the test seeds its invented tenant."""
    if request.param == "fake":
        return FakeTeams(clock=clock)
    graph = FakeGraph(TEACHER)
    area = GraphTeams(GraphClient(token=lambda: _token(), transport=graph.transport), clock=clock)
    return Tenant(area, graph)


async def _token() -> str:
    return "token"


class Tenant:
    """The real area plus the fake Microsoft behind it."""

    def __init__(self, area: GraphTeams, graph: FakeGraph):
        self.area, self.graph = area, graph
        self.add_team, self.add_member = graph.add_team, graph.add_member
        self.remove_member, self.make_owner = graph.remove_member, graph.make_owner
        self.event_of = graph.event_of
        self.add_channel, self.add_meeting = graph.add_channel, graph.add_meeting
        self.reschedule, self.cancel = graph.reschedule, graph.cancel

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


def _at(day: int, hour: int = 10, month: int = 9) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=WARSAW)


async def _two_classes(tenant):
    """2A has Jan and Ewa, 3B has Adam; Zofia is in neither."""
    team_a, a = await _class_with_jan(tenant)
    tenant.add_member(team_a, "Ewa Zielinska")
    await tenant.sync_roster(a.id)
    team_b = tenant.add_team("3B matematyka")
    tenant.add_member(team_b, "Adam Lis")
    return team_a, a, await tenant.link_team(team_b)


JAN, EWA, ADAM, ZOFIA = (
    f"{n}@example.org" for n in ("jan.kowalski", "ewa.zielinska", "adam.lis", "zofia.nowicka")
)


async def test_a_meeting_made_in_a_class_channel_is_attached_to_that_class(tenant):
    team, a, b = await _two_classes(tenant)
    channel = tenant.add_channel(team, "Zadania")
    meeting = tenant.add_meeting(
        "Konsultacje", _at(12), _at(12, 11), attendees=[ZOFIA], channel=channel
    )

    await tenant.sync_calendar()

    [lesson] = await tenant.list_lessons(a.id)
    assert (lesson.id, lesson.start, lesson.end) == (meeting, _at(12), _at(12, 11))
    assert lesson.join_url and not lesson.cancelled and lesson.topic is None
    assert await tenant.list_lessons(b.id) == []
    assert await tenant.list_calendar_questions() == []


async def test_a_meeting_whose_invitees_are_exactly_one_classs_students_is_attached(tenant):
    _, a, b = await _two_classes(tenant)
    meeting = tenant.add_meeting("Powtorka", _at(12), _at(12, 11), attendees=[EWA, JAN])

    await tenant.sync_calendar()

    assert [x.id for x in await tenant.list_lessons(a.id)] == [meeting]
    assert await tenant.list_lessons(b.id) == []
    assert await tenant.list_calendar_questions() == []


async def test_a_time_change_in_teams_updates_the_lesson(tenant):
    _, a, _ = await _two_classes(tenant)
    meeting = tenant.add_meeting("Powtorka", _at(12), _at(12, 11), attendees=[EWA, JAN])
    await tenant.sync_calendar()

    tenant.reschedule(meeting, _at(14, 13), _at(14, 14))
    await tenant.sync_calendar()

    [lesson] = await tenant.list_lessons(a.id)
    assert (lesson.start, lesson.end, lesson.cancelled) == (_at(14, 13), _at(14, 14), False)


async def test_a_cancellation_in_teams_keeps_the_lesson_marked_cancelled(tenant):
    _, a, _ = await _two_classes(tenant)
    meeting = tenant.add_meeting("Powtorka", _at(12), _at(12, 11), attendees=[EWA, JAN])
    await tenant.sync_calendar()

    tenant.cancel(meeting)
    await tenant.sync_calendar()

    [lesson] = await tenant.list_lessons(a.id)
    assert (lesson.id, lesson.start, lesson.cancelled) == (meeting, _at(12), True)


async def test_teams_wins_on_the_time_and_cancellation_of_timetable_lessons(tenant):
    _, linked = await _class_with_jan(tenant)
    await tenant.add_timetable(linked.id, [MONDAY_8], YEAR_END)
    before = await tenant.list_lessons(linked.id)
    await tenant.sync_calendar()

    tenant.reschedule(before[0].id, _at(7, 9), _at(7, 10))
    tenant.cancel(before[1].id)
    await tenant.sync_calendar()

    after = await tenant.list_lessons(linked.id)
    assert len(after) == len(before)
    assert [(x.start, x.cancelled) for x in after[:3]] == [
        (_at(7, 9), False),
        (before[1].start, True),
        (before[2].start, False),
    ]


async def test_a_cancelled_single_lesson_keeps_its_topic(tenant):
    _, linked = await _class_with_jan(tenant)
    lesson = await tenant.add_lesson(linked.id, _at(12), _at(12, 11), "Funkcje liniowe")
    await tenant.sync_calendar()

    tenant.cancel(lesson.id)
    await tenant.sync_calendar()

    [kept] = await tenant.list_lessons(linked.id)
    assert (kept.id, kept.topic, kept.cancelled) == (lesson.id, "Funkcje liniowe", True)


async def test_a_series_overlapping_several_classes_asks_which_once_for_every_occurrence(tenant):
    _, a, b = await _two_classes(tenant)
    series = tenant.add_meeting(
        "Kolo naukowe",
        _at(2, 15),
        _at(2, 16),
        attendees=[JAN, ADAM],
        weekly_until=date(2026, 9, 16),
    )

    await tenant.sync_calendar()
    await tenant.sync_calendar()

    [question] = await tenant.list_calendar_questions()
    assert question.id == series
    assert question.subject == "Kolo naukowe"
    assert question.start == _at(2, 15)
    assert sorted(question.candidates) == sorted([a.id, b.id])
    assert await tenant.list_lessons(a.id) == []

    await tenant.answer_calendar_question(question.id, b.id)

    assert [x.start.day for x in await tenant.list_lessons(b.id)] == [2, 9, 16]
    assert await tenant.list_lessons(a.id) == []
    assert await tenant.list_calendar_questions() == []


async def test_only_a_candidate_class_or_keep_or_hide_answers_a_question(tenant):
    await _two_classes(tenant)
    other = await tenant.link_team(tenant.add_team("1C matematyka"))
    tenant.add_meeting("Kolo naukowe", _at(12), _at(12, 11), attendees=[JAN, ADAM])
    await tenant.sync_calendar()
    [question] = await tenant.list_calendar_questions()

    with pytest.raises(ValueError):
        await tenant.answer_calendar_question(question.id, other.id)
    with pytest.raises(ValueError):
        await tenant.answer_calendar_question("no-such-question", "keep")
    assert len(await tenant.list_calendar_questions()) == 1


@pytest.mark.parametrize("answer", ["keep", "hide"])
async def test_a_meeting_matching_no_class_asks_keep_or_hide_once_per_series(tenant, answer):
    _, a, b = await _two_classes(tenant)
    tenant.add_meeting(
        "Rada pedagogiczna",
        _at(2, 15),
        _at(2, 16),
        attendees=[ZOFIA],
        weekly_until=date(2026, 9, 16),
    )
    await tenant.sync_calendar()
    [question] = await tenant.list_calendar_questions()
    assert question.candidates == []

    await tenant.answer_calendar_question(question.id, answer)
    await tenant.sync_calendar()

    assert await tenant.list_calendar_questions() == []
    assert await tenant.list_lessons(a.id) + await tenant.list_lessons(b.id) == []


async def test_the_calendar_window_runs_7_days_back_and_60_ahead(tenant, clock):
    _, a, _ = await _two_classes(tenant)
    old = tenant.add_meeting("Za stare", _at(24, month=8), _at(24, 11, 8), attendees=[JAN, EWA])
    near = tenant.add_meeting("Blisko", _at(26, month=8), _at(26, 11, 8), attendees=[JAN, EWA])
    far = tenant.add_meeting("Daleko", _at(5, month=11), _at(5, 11, 11), attendees=[JAN, EWA])

    await tenant.sync_calendar()
    assert [x.id for x in await tenant.list_lessons(a.id)] == [near]

    clock.advance(days=40)
    await tenant.sync_calendar()
    ids = {x.id for x in await tenant.list_lessons(a.id)}
    assert ids == {near, far}
    assert old not in ids


async def test_calendar_sync_is_a_job_that_runs_every_15_minutes(tenant, monkeypatch):
    _, a, _ = await _two_classes(tenant)
    meeting = tenant.add_meeting("Powtorka", _at(12), _at(12, 11), attendees=[EWA, JAN])
    monkeypatch.setattr(teams, "backend", lambda: tenant)

    await handlers.sync_calendar(Job(kind="teams.sync_calendar", payload={}), _ignore)

    assert [x.id for x in await tenant.list_lessons(a.id)] == [meeting]
    await schedule.sync_declared()
    async with sessions()() as session:
        row = await session.get(Schedule, "teams.sync-calendar")
    assert (row.kind, row.every_seconds) == ("teams.sync_calendar", 15 * 60)


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
