"""The Reminder through the `teams` interface, against the real area over FakeGraph and against
FakeTeams: a count-only post in General a day before the due time. Time moves with `clock`."""

from datetime import datetime, timedelta

import pytest
from tenant import CLOSE, DUE, PDF, ignore, make_class
from tenant import spec as _spec

from classlop import teams
from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.shared.models import Job, Schedule
from classlop.teams import handlers, reminders
from classlop.teams.assignment_records import AssignmentRecord
from classlop.teams.fake import FakeTeams


async def _move_due(tenant, given, due: datetime):
    """The due time changes, as a change to a Given Assignment will do; nothing else does here."""
    if isinstance(tenant, FakeTeams):
        tenant._save(given.id, due_at=due)
        return
    async with sessions().begin() as session:
        (await session.get_one(AssignmentRecord, given.id)).due_at = due


async def _schedule_row(given):
    async with sessions()() as session:
        return await session.get(Schedule, f"teams.remind:{given.id}")


async def _scheduled(given) -> Schedule:
    row = await _schedule_row(given)
    assert row, "no Reminder is scheduled"
    return row


async def _fire(tenant, monkeypatch, given):
    """The schedule's job runs, as the worker would at the due-minus-24-hours moment."""
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    job = Job(kind="teams.remind_assignment", payload={"assignment_id": given.id})
    await handlers.remind_assignment(job, ignore)


def _reminders(tenant, klass) -> list[str]:
    """What was posted in General after the Assignment's own post."""
    return [p.html for p in tenant.channel_posts(klass.team_id)[1:]]


async def _hand_in(tenant, clock, user):
    tenant.upload(user, "praca.jpg", b"page")
    clock.advance(minutes=3)
    await tenant.poll_handins()


async def test_giving_more_than_a_day_before_the_due_time_schedules_a_reminder_for_a_day_before(
    tenant, gave
):
    klass, _ = await make_class(tenant, "Jan Kowalski")

    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    row = await _scheduled(given)
    assert row.next_at == DUE - timedelta(hours=24)
    assert (row.kind, row.payload) == ("teams.remind_assignment", {"assignment_id": given.id})


async def test_the_reminder_says_how_many_students_have_not_handed_in_and_not_who(
    tenant, gave, clock, monkeypatch
):
    klass, users = await make_class(tenant, "Jan Kowalski", "Ewa Zielinska", "Adam Nowak")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    await _hand_in(tenant, clock, users["Jan Kowalski"])
    clock.now = DUE - timedelta(hours=24)

    await _fire(tenant, monkeypatch, given)

    [reminder] = _reminders(tenant, klass)
    assert "Jeszcze nie oddało: 2 osoby." in reminder
    assert "Funkcje liniowe" in reminder
    assert not any(n in reminder for n in ("Jan", "Ewa", "Adam", "Kowalski"))


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (1, "1 osoba"),
        (2, "2 osoby"),
        (4, "4 osoby"),
        (5, "5 osób"),
        (7, "7 osób"),
        (11, "11 osób"),
        (12, "12 osób"),
        (14, "14 osób"),
        (21, "21 osób"),
        (22, "22 osoby"),
        (25, "25 osób"),
        (112, "112 osób"),
    ],
)
def test_the_count_takes_the_polish_plural_form(count, text):
    assert reminders.count_text(count) == text


async def test_a_single_student_is_counted_in_the_singular(tenant, gave, clock, monkeypatch):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    clock.now = DUE - timedelta(hours=24)

    await _fire(tenant, monkeypatch, given)

    assert "Jeszcze nie oddało: 1 osoba." in _reminders(tenant, klass)[0]


async def test_an_assignment_given_a_day_or_less_before_the_due_time_gets_no_reminder(
    tenant, gave, clock
):
    klass, _ = await make_class(tenant, "Jan Kowalski")

    exactly_a_day = await tenant.give_assignment(
        klass.id, _spec(due_at=clock.now + timedelta(hours=24), close_at=DUE), PDF
    )
    a_quiz = await tenant.give_assignment(
        klass.id, _spec(due_at=clock.now + timedelta(hours=2), close_at=DUE), PDF
    )

    assert await _schedule_row(exactly_a_day) is None
    assert await _schedule_row(a_quiz) is None


async def test_a_scheduled_assignment_gets_its_reminder_when_it_is_given(tenant, gave, clock):
    klass, _ = await make_class(tenant, "Jan Kowalski")

    given = await tenant.give_assignment(klass.id, _spec(), PDF, clock.now + timedelta(days=2))

    assert given.state == "scheduled"
    assert (await _scheduled(given)).next_at == DUE - timedelta(hours=24)


async def test_the_reminder_is_skipped_while_the_assignment_is_not_yet_posted(
    tenant, gave, clock, monkeypatch
):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF, DUE - timedelta(hours=23))
    clock.now = DUE - timedelta(hours=23, minutes=30)

    await _fire(tenant, monkeypatch, given)

    assert tenant.channel_posts(klass.team_id) == []


async def test_the_reminder_is_skipped_when_everyone_has_handed_in(
    tenant, gave, clock, monkeypatch
):
    klass, users = await make_class(tenant, "Jan Kowalski", "Ewa Zielinska")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    for user in users.values():
        await _hand_in(tenant, clock, user)
    clock.now = DUE - timedelta(hours=24)

    await _fire(tenant, monkeypatch, given)

    assert _reminders(tenant, klass) == []


async def test_a_reminder_switched_off_at_giving_is_never_scheduled(tenant, gave):
    klass, _ = await make_class(tenant, "Jan Kowalski")

    given = await tenant.give_assignment(klass.id, _spec(reminder_on=False), PDF)

    assert await _schedule_row(given) is None


async def test_switching_the_reminder_off_and_on_removes_and_restores_it(
    tenant, gave, clock, monkeypatch
):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    off = await tenant.set_reminder(given.id, False)
    assert (off.reminder_on, await _schedule_row(given)) == (False, None)
    clock.now = DUE - timedelta(hours=24)
    await _fire(tenant, monkeypatch, given)  # a job already on its way still posts nothing
    assert _reminders(tenant, klass) == []

    clock.now = DUE - timedelta(days=3)
    on = await tenant.set_reminder(given.id, True)
    assert on.reminder_on
    assert (await _scheduled(given)).next_at == DUE - timedelta(hours=24)


async def test_the_count_leaves_out_former_students_the_assignment_never_reached(
    tenant, gave, clock, monkeypatch
):
    klass, users = await make_class(tenant, "Jan Kowalski", "Ewa Zielinska", "Adam Nowak")
    tenant.reject_chats(users["Ewa Zielinska"])
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    tenant.remove_member(klass.team_id, users["Ewa Zielinska"])
    await tenant.sync_roster(klass.id)
    clock.now = DUE - timedelta(hours=24)

    await _fire(tenant, monkeypatch, given)

    assert "Jeszcze nie oddało: 2 osoby." in _reminders(tenant, klass)[0]


async def test_the_reminder_is_skipped_once_the_assignment_is_closed(
    tenant, gave, clock, monkeypatch
):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    clock.now = CLOSE
    await tenant.poll_handins()
    assert (await tenant.get_assignment(given.id)).state == "closed"
    clock.now = DUE - timedelta(hours=24)  # even a job that fires out of turn

    await _fire(tenant, monkeypatch, given)

    assert _reminders(tenant, klass) == []
    with pytest.raises(ValueError):
        await tenant.set_reminder(given.id, True)


async def test_the_reminder_waits_for_its_day(tenant, gave, clock, monkeypatch):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    await _fire(tenant, monkeypatch, given)
    clock.now = DUE + timedelta(minutes=1)
    await _fire(tenant, monkeypatch, given)

    assert _reminders(tenant, klass) == []


async def test_a_moved_due_time_moves_the_reminder_and_repeating_it_changes_nothing(
    tenant, gave, clock, monkeypatch
):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    later = DUE + timedelta(days=2)

    await _move_due(tenant, given, later)
    await tenant.reschedule_reminder(given.id)
    await tenant.reschedule_reminder(given.id)

    assert (await _scheduled(given)).next_at == later - timedelta(hours=24)
    clock.now = later - timedelta(hours=24)
    await _fire(tenant, monkeypatch, given)
    assert len(_reminders(tenant, klass)) == 1


async def test_a_due_time_moved_to_less_than_a_day_away_removes_the_reminder(tenant, gave, clock):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    clock.now = DUE - timedelta(days=2)

    await _move_due(tenant, given, clock.now + timedelta(hours=10))
    await tenant.reschedule_reminder(given.id)

    assert await _schedule_row(given) is None


async def test_deleting_the_class_cancels_the_reminder_and_a_late_job_ends_quietly(
    tenant, gave, monkeypatch
):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    assert await _schedule_row(given)

    await tenant.delete_class(klass.id, "2A matematyka")

    assert await _schedule_row(given) is None
    await _fire(tenant, monkeypatch, given)


async def test_a_read_only_class_gets_no_reminder(tenant, gave, clock, monkeypatch):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    tenant.delete_team(klass.team_id)
    await tenant.sync_roster(klass.id)
    clock.now = DUE - timedelta(hours=24)

    await _fire(tenant, monkeypatch, given)

    assert _reminders(tenant, klass) == []


async def test_a_reminder_that_cannot_be_posted_fails_its_job_for_a_retry(
    tenant, gave, clock, monkeypatch
):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    tenant.reject_posts(klass.team_id)
    clock.now = DUE - timedelta(hours=24)

    with pytest.raises(Exception):  # noqa: B017 - GraphError or the fake's refusal
        await _fire(tenant, monkeypatch, given)

    tenant.accept_posts(klass.team_id)
    await _fire(tenant, monkeypatch, given)
    assert len(_reminders(tenant, klass)) == 1


async def test_a_lapsed_sign_in_parks_the_reminder(tenant, gave, clock):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    clock.now = DUE - timedelta(hours=24)
    tenant.lapse_sign_in()

    with pytest.raises(SignInRequired):
        await tenant.post_reminder(given.id)
