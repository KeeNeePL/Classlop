"""One contract suite for the `teams` interface, run against the real area over FakeGraph (with
Postgres from compose) and against FakeTeams, so the two cannot drift."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

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
    client = GraphClient(token=lambda: _token(), transport=graph.transport, sleep=_ignore)
    area = GraphTeams(client, clock=clock)
    return Tenant(area, graph)


async def _token() -> str:
    return "token"


class Tenant:
    """The real area plus the fake Microsoft behind it."""

    def __init__(self, area: GraphTeams, graph: FakeGraph):
        self.area, self.graph = area, graph
        self.add_team, self.add_member = graph.add_team, graph.add_member
        self.remove_member, self.make_owner = graph.remove_member, graph.make_owner
        self.add_user, self.rename_team = graph.add_user, graph.rename_team
        self.team_members, self.team_name = graph.team_members, graph.team_name
        self.team_is_private = graph.team_is_private

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


async def test_creating_a_class_creates_a_private_team_with_the_picked_students(tenant):
    jan = tenant.add_user("Jan Kowalski")
    ewa = tenant.add_user("Ewa Zielinska")

    created = await tenant.create_class("2A matematyka", [jan, ewa])

    assert created.name == "2A matematyka"
    assert created.general_channel_id
    assert await tenant.get_class(created.id) == created
    assert sorted(s.display_name for s in await tenant.list_students(created.id)) == [
        "Ewa Zielinska",
        "Jan Kowalski",
    ]
    assert [t.id for t in await tenant.list_owned_teams()] == [created.team_id]
    assert tenant.team_is_private(created.team_id)


async def test_a_created_class_cannot_be_linked_again(tenant):
    created = await tenant.create_class("2A matematyka", [])

    with pytest.raises(teams.AlreadyLinked):
        await tenant.link_team(created.team_id)


async def test_searching_tenant_users_finds_candidates_by_name(tenant):
    jan = tenant.add_user("Jan Kowalski")
    tenant.add_user("Ewa Zielinska")
    tenant.add_user("Janina Nowicka")

    found = await tenant.search_users("kowal")
    assert [(c.user_id, c.display_name) for c in found] == [(jan, "Jan Kowalski")]
    assert found[0].upn == "jan.kowalski@example.org"
    assert [c.display_name for c in await tenant.search_users("jan")] == [
        "Jan Kowalski",
        "Janina Nowicka",
    ]


async def test_adding_a_student_adds_them_to_the_team(tenant):
    created = await tenant.create_class("2A matematyka", [])
    jan = tenant.add_user("Jan Kowalski")

    student = await tenant.add_student(created.id, jan)

    assert (student.display_name, student.former_since) == ("Jan Kowalski", None)
    assert [s.id for s in await tenant.list_students(created.id)] == [student.id]
    assert jan in tenant.team_members(created.team_id)


async def test_removing_a_student_removes_them_from_the_team_and_keeps_a_former_student(
    tenant, clock
):
    jan = tenant.add_user("Jan Kowalski")
    ewa = tenant.add_user("Ewa Zielinska")
    created = await tenant.create_class("2A matematyka", [jan, ewa])

    await tenant.remove_student(created.id, jan)

    assert jan not in tenant.team_members(created.team_id)
    by_name = {s.display_name: s for s in await tenant.list_students(created.id)}
    assert by_name["Jan Kowalski"].former_since == clock.now
    assert by_name["Ewa Zielinska"].former_since is None


async def test_renaming_a_class_renames_its_team(tenant):
    created = await tenant.create_class("2A matematyka", [])

    renamed = await tenant.rename_class(created.id, "2A mat-fiz")

    assert renamed.name == "2A mat-fiz"
    assert (await tenant.get_class(created.id)).name == "2A mat-fiz"
    assert tenant.team_name(created.team_id) == "2A mat-fiz"


async def test_a_team_renamed_in_teams_renames_the_class_on_the_next_sync(tenant):
    created = await tenant.create_class("2A matematyka", [])

    tenant.rename_team(created.team_id, "2B matematyka")
    assert (await tenant.get_class(created.id)).name == "2A matematyka"
    await tenant.sync_roster(created.id)

    assert (await tenant.get_class(created.id)).name == "2B matematyka"
