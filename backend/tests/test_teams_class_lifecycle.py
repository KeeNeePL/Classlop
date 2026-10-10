"""Deleting a Class, and a team deleted in Teams, through the `teams` interface: against the real
area over FakeGraph and against FakeTeams."""

import asyncio
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from tenant import ignore

from classlop import items, teams
from classlop.shared import storage
from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.shared.models import Job, Schedule
from classlop.teams import handlers

WARSAW = ZoneInfo("Europe/Warsaw")
PDF = b"%PDF-1.7 funkcje liniowe"
DUE = datetime(2026, 9, 15, 20, 0, tzinfo=WARSAW)
CLOSE = datetime(2026, 9, 17, 20, 0, tzinfo=WARSAW)


@pytest.fixture(autouse=True)
def frozen_items(monkeypatch):
    """Items are pinned by a stand-in for `items.give`; deleting a Class must never call it."""

    async def give(item_ids, assignment_id, class_id, given_at):
        return [uuid.uuid4() for _ in item_ids]

    monkeypatch.setattr(items, "give", give)


def _spec() -> teams.AssignmentSpec:
    return teams.AssignmentSpec(
        title="Funkcje liniowe",
        type="homework",
        due_at=DUE,
        close_at=CLOSE,
        item_ids=[uuid.UUID(int=1)],
    )


async def _class(tenant, name: str = "2A matematyka", *students: str):
    team = tenant.add_team(name)
    users = {s: tenant.add_member(team, s) for s in students}
    return await tenant.link_team(team), users


async def test_deleting_a_class_needs_its_name_typed_and_deletes_its_team(tenant):
    klass, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")

    with pytest.raises(ValueError):
        await tenant.delete_class(klass.id, "2B matematyka")
    assert await tenant.list_classes() == [klass]

    await tenant.delete_class(klass.id, "2A matematyka")

    assert await tenant.list_classes() == []
    assert klass.team_id not in {t.id for t in await tenant.list_owned_teams()}


async def test_deleting_a_class_removes_its_future_lessons_from_the_calendar_not_the_past(
    tenant, clock
):
    klass, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")
    mondays = [teams.Slot(weekday=0, start=time(9, 0), end=time(9, 45))]
    await tenant.add_timetable(klass.id, mondays, date(2026, 10, 30))
    for day in (30, 44):  # a past and a future single Lesson
        start = datetime(2026, 9, 1, 10, tzinfo=WARSAW) + timedelta(days=day)
        await tenant.add_lesson(klass.id, start, start + timedelta(minutes=45), "Funkcje")
    clock.advance(days=34)  # Monday 5 October, 10:00: today's Lesson has begun
    window = (date(2026, 9, 1), date(2026, 12, 31))
    assert len(await tenant.calendar_dates(*window)) == 10

    await tenant.delete_class(klass.id, "2A matematyka")

    assert await tenant.calendar_dates(*window) == [
        date(2026, 9, 7),
        date(2026, 9, 14),
        date(2026, 9, 21),
        date(2026, 9, 28),
        date(2026, 10, 1),
        date(2026, 10, 5),
    ]


async def _schedule_row(name: str):
    async with sessions()() as session:
        return await session.get(Schedule, name)


async def test_deleting_a_class_deletes_hand_in_folders_and_schedules_but_keeps_the_chats(
    tenant, clock
):
    klass, users = await _class(tenant, "2A matematyka", "Jan Kowalski", "Ewa Zielinska")
    jan = users["Jan Kowalski"]
    await tenant.give_assignment(klass.id, _spec(), PDF)
    later = await tenant.give_assignment(klass.id, _spec(), PDF, when=clock.now + timedelta(days=3))
    assert await _schedule_row(f"teams.give:{later.id}")
    assert len(tenant.shared_with(jan)) == 1
    notice = tenant.chat_messages(jan)

    await tenant.delete_class(klass.id, "2A matematyka")

    assert tenant.shared_with(jan) == []
    assert tenant.shared_with(users["Ewa Zielinska"]) == []
    assert await _schedule_row(f"teams.give:{later.id}") is None
    assert tenant.chat_messages(jan) == notice


async def test_deleting_a_class_deletes_its_onedrive_folder_and_leaves_other_classes_alone(
    tenant, clock
):
    one, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")
    other, _ = await _class(tenant, "2B matematyka", "Ewa Zielinska")
    for klass in (one, other):
        await tenant.give_assignment(klass.id, _spec(), PDF)
        await tenant.give_assignment(klass.id, _spec(), PDF)
    assert tenant.class_folders() == ["Classlop/2A matematyka", "Classlop/2B matematyka"]

    await tenant.delete_class(one.id, "2A matematyka")

    assert tenant.class_folders() == ["Classlop/2B matematyka"]


async def test_a_team_deleted_in_teams_makes_its_class_read_only_until_it_is_dealt_with(
    tenant, clock
):
    klass, users = await _class(tenant, "2A matematyka", "Jan Kowalski")
    other = tenant.add_user("Ewa Zielinska")
    assert await tenant.list_deleted_teams() == []

    tenant.delete_team(klass.team_id)
    await tenant.sync_roster(klass.id)

    [held] = await tenant.list_deleted_teams()
    assert (held.id, held.state, held.team_deleted_at) == (klass.id, "team_deleted", clock.now)
    assert await tenant.get_class(klass.id) == held
    assert [s.display_name for s in await tenant.list_students(klass.id)] == ["Jan Kowalski"]
    slot = teams.Slot(weekday=0, start=time(9, 0), end=time(9, 45))
    start = datetime(2026, 9, 7, 9, tzinfo=WARSAW)
    for call in (
        tenant.add_student(klass.id, other),
        tenant.remove_student(klass.id, users["Jan Kowalski"]),
        tenant.rename_class(klass.id, "2B matematyka"),
        tenant.add_timetable(klass.id, [slot], date(2026, 10, 30)),
        tenant.add_lesson(klass.id, start, start + timedelta(minutes=45), "Funkcje"),
        tenant.give_assignment(klass.id, _spec(), PDF),
    ):
        with pytest.raises(teams.ClassReadOnly):
            await call


async def test_a_team_restored_in_teams_relinks_its_class_on_the_next_sync(tenant):
    klass, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")
    tenant.delete_team(klass.team_id)
    await tenant.sync_roster(klass.id)
    assert [c.id for c in await tenant.list_deleted_teams()] == [klass.id]

    tenant.undelete_team(klass.team_id)
    await tenant.sync_roster(klass.id)

    assert await tenant.list_deleted_teams() == []
    restored = await tenant.get_class(klass.id)
    assert (restored.state, restored.team_deleted_at) == ("active", None)
    assert [s.display_name for s in await tenant.list_students(klass.id)] == ["Jan Kowalski"]
    await tenant.rename_class(klass.id, "2B matematyka")


async def test_restoring_the_team_from_classlop_makes_the_class_active_again(tenant):
    klass, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")
    tenant.delete_team(klass.team_id)
    await tenant.sync_roster(klass.id)

    restored = await tenant.restore_team(klass.id)

    assert restored.state == "active"
    assert klass.team_id in {t.id for t in await tenant.list_owned_teams()}
    assert await tenant.list_deleted_teams() == []


async def test_a_team_still_deleted_after_30_days_deletes_its_class(tenant, clock):
    klass, users = await _class(tenant, "2A matematyka", "Jan Kowalski")
    await tenant.give_assignment(klass.id, _spec(), PDF)
    tenant.delete_team(klass.team_id)
    await tenant.sync_roster(klass.id)

    clock.advance(days=30, seconds=-1)
    await tenant.sync_roster(klass.id)
    assert [c.id for c in await tenant.list_deleted_teams()] == [klass.id]

    clock.advance(seconds=1)
    await tenant.sync_roster(klass.id)

    assert await tenant.list_classes() == []
    assert tenant.shared_with(users["Jan Kowalski"]) == []


async def test_a_class_whose_team_is_deleted_can_be_deleted_by_typing_its_name(tenant):
    klass, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")
    tenant.delete_team(klass.team_id)
    await tenant.sync_roster(klass.id)

    await tenant.delete_class(klass.id, "2A matematyka")

    assert await tenant.list_classes() == []
    assert await tenant.list_deleted_teams() == []


async def test_the_roster_job_finds_a_team_deleted_in_teams(tenant, monkeypatch):
    klass, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    tenant.delete_team(klass.team_id)

    await handlers.sync_rosters(Job(kind="teams.sync_rosters", payload={}), ignore)

    assert [c.id for c in await tenant.list_deleted_teams()] == [klass.id]


async def test_what_needs_teams_waits_for_a_lapsed_sign_in(tenant):
    klass, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")
    held, _ = await _class(tenant, "2B matematyka", "Ewa Zielinska")
    tenant.delete_team(held.team_id)
    await tenant.sync_roster(held.id)
    tenant.lapse_sign_in()

    for call in (
        tenant.delete_class(klass.id, "2A matematyka"),
        tenant.restore_team(held.id),
    ):
        with pytest.raises(SignInRequired):
            await call


async def test_the_items_pdf_kept_in_storage_goes_with_the_class(tenant):
    if not hasattr(tenant, "area"):
        pytest.skip("FakeTeams keeps no storage")
    klass, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    key = f"teams/assignments/{given.id}/items.pdf"
    assert await asyncio.to_thread(storage.get, key) == PDF

    await tenant.delete_class(klass.id, "2A matematyka")

    with pytest.raises(Exception, match="NoSuchKey"):
        await asyncio.to_thread(storage.get, key)


async def test_a_retry_job_of_a_deleted_class_ends_quietly(tenant, monkeypatch):
    klass, _ = await _class(tenant, "2A matematyka", "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    await tenant.delete_class(klass.id, "2A matematyka")
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    payload = {"assignment_id": given.id}

    await handlers.deliver_assignment(
        Job(kind="teams.deliver_assignment", payload=payload, attempts=1), ignore
    )
    await handlers.give_assignment(
        Job(kind="teams.give_assignment", payload=payload, attempts=1), ignore
    )


async def test_the_copies_of_hand_ins_kept_in_storage_go_with_the_class(tenant, clock):
    klass, users = await _class(tenant, "2A matematyka", "Jan Kowalski")
    await tenant.give_assignment(klass.id, _spec(), PDF)
    tenant.upload(users["Jan Kowalski"], "strona-1.jpg", b"page one")
    clock.advance(minutes=3)
    await tenant.poll_handins()
    (given,) = await tenant.list_assignments(klass.id)
    (mine,) = await tenant.list_submissions(given.id)
    assert await asyncio.to_thread(storage.get, mine.files[0]) == b"page one"

    await tenant.delete_class(klass.id, "2A matematyka")

    with pytest.raises(Exception, match="NoSuchKey"):
        await asyncio.to_thread(storage.get, mine.files[0])
