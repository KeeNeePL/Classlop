"""Hand-ins becoming Submissions through the `teams` interface, against the real area over
FakeGraph and against FakeTeams. A Student's upload is `tenant.upload`, time moves with `clock`."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from tenant import PDF, ignore, make_class
from tenant import spec as _spec

from classlop import teams
from classlop.grading.graph import GradeJob
from classlop.shared import storage
from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.shared.models import Job
from classlop.shared.schedule import _declared
from classlop.teams import handlers, ids


async def _given(tenant, *names, **changes):
    klass, users = await make_class(tenant, *names)
    given = await tenant.give_assignment(klass.id, _spec(**changes), PDF)
    return klass, users, given


async def _submission(tenant, klass, given, name):
    student = next(s for s in await tenant.list_students(klass.id) if s.display_name == name)
    return next(s for s in await tenant.list_submissions(given.id) if s.student_id == student.id)


async def _grading_jobs(submission) -> list[GradeJob]:
    async with sessions()() as session:
        jobs = await session.scalars(
            select(Job).where(
                Job.kind == "grading.grade",
                Job.payload["submission_id"].astext == str(ids.as_uuid(submission.id)),
            )
        )
    return sorted((GradeJob.model_validate(j.payload) for j in jobs), key=lambda j: j.handed_in_at)


async def _hand_in(tenant, clock, user, *pages: bytes):
    """The Student uploads one page a minute, then three quiet minutes pass and the poll runs."""
    for number, page in enumerate(pages, 1):
        tenant.upload(user, f"strona-{number}-{len(page)}.jpg", page)
        clock.advance(minutes=1)
    clock.advance(minutes=2)
    await tenant.poll_handins()


async def test_files_become_a_handed_in_submission_after_three_quiet_minutes(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    jan = users["Jan Kowalski"]

    tenant.upload(jan, "strona-1.jpg", b"page one")
    clock.advance(minutes=1)
    tenant.upload(jan, "strona-2.jpg", b"page two")
    last = clock.now
    clock.advance(minutes=2, seconds=59)
    await tenant.poll_handins()
    assert (await _submission(tenant, klass, given, "Jan Kowalski")).state == "not_handed_in"
    clock.advance(seconds=1)
    await tenant.poll_handins()

    mine = await _submission(tenant, klass, given, "Jan Kowalski")
    assert (mine.state, mine.handed_in_at, mine.late) == ("handed_in", last, False)
    assert [storage.get(key) for key in mine.files] == [b"page one", b"page two"]
    assert all(key.startswith("teams/submissions/") for key in mine.files)
    assert (await _submission(tenant, klass, given, "Ewa Zielinska")).state == "not_handed_in"


async def test_a_settled_hand_in_enqueues_one_grading_job_with_its_items_and_files(
    tenant, gave, clock
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    await _hand_in(tenant, clock, users["Jan Kowalski"], b"one", b"two")
    await tenant.poll_handins()
    await tenant.poll_handins()

    mine = await _submission(tenant, klass, given, "Jan Kowalski")
    [job] = await _grading_jobs(mine)
    assert job.submission_id == ids.as_uuid(mine.id)
    assert job.assignment_id == ids.as_uuid(given.id)
    assert (job.handed_in_at, job.due_at) == (mine.handed_in_at, given.due_at)
    assert [(i.id, i.number) for i in job.items] == [
        (given.item_versions[0], 1),
        (given.item_versions[1], 2),
    ]
    assert job.files == mine.files


async def test_a_hand_in_after_the_due_time_is_a_late_submission_by_the_servers_time(
    tenant, gave, clock
):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    clock.now = given.due_at - timedelta(minutes=1)
    tenant.upload(users["Ewa Zielinska"], "a.jpg", b"on time")
    clock.advance(minutes=2)
    tenant.upload(users["Jan Kowalski"], "b.jpg", b"late")
    late_at = clock.now
    clock.advance(minutes=3)

    await tenant.poll_handins()

    ewa = await _submission(tenant, klass, given, "Ewa Zielinska")
    jan = await _submission(tenant, klass, given, "Jan Kowalski")
    assert (ewa.state, ewa.late) == ("handed_in", False)
    assert (jan.state, jan.late, jan.handed_in_at) == ("handed_in", True, late_at)


async def test_a_change_before_return_replaces_the_whole_hand_in_and_regrades_it(
    tenant, gave, clock
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    await _hand_in(tenant, clock, jan, b"one")
    first = await _submission(tenant, klass, given, "Jan Kowalski")

    tenant.upload(jan, "dodatkowa.jpg", b"two-pages")
    clock.advance(minutes=3)
    await tenant.poll_handins()

    second = await _submission(tenant, klass, given, "Jan Kowalski")
    assert second.state == "handed_in"
    assert second.handed_in_at > first.handed_in_at
    assert [storage.get(k) for k in second.files] == [b"one", b"two-pages"]
    assert [j.files for j in await _grading_jobs(second)] == [first.files, second.files]


async def test_a_file_replaced_by_the_student_replaces_the_hand_in(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    tenant.upload(jan, "strona.jpg", b"blurred")
    clock.advance(minutes=3)
    await tenant.poll_handins()
    tenant.upload(jan, "strona.jpg", b"sharp")
    clock.advance(minutes=3)

    await tenant.poll_handins()

    mine = await _submission(tenant, klass, given, "Jan Kowalski")
    assert [storage.get(k) for k in mine.files] == [b"sharp"]
    assert len(await _grading_jobs(mine)) == 2


async def test_deleting_every_file_returns_to_not_handed_in(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    tenant.upload(jan, "strona.jpg", b"one")
    clock.advance(minutes=3)
    await tenant.poll_handins()

    tenant.delete_file(jan, "strona.jpg")
    await tenant.poll_handins()  # a deletion is timed by when the poll sees it
    clock.advance(minutes=3)
    await tenant.poll_handins()

    mine = await _submission(tenant, klass, given, "Jan Kowalski")
    assert (mine.state, mine.handed_in_at, mine.late, mine.files) == (
        "not_handed_in",
        None,
        False,
        [],
    )
    tenant.upload(jan, "druga.jpg", b"again")
    clock.advance(minutes=3)
    await tenant.poll_handins()
    assert (await _submission(tenant, klass, given, "Jan Kowalski")).state == "handed_in"


async def test_deleting_one_of_two_files_regrades_what_is_left(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    tenant.upload(jan, "a.jpg", b"one")
    tenant.upload(jan, "b.jpg", b"two")
    clock.advance(minutes=3)
    await tenant.poll_handins()
    first = await _submission(tenant, klass, given, "Jan Kowalski")

    tenant.delete_file(jan, "b.jpg")
    await tenant.poll_handins()
    clock.advance(minutes=3)
    await tenant.poll_handins()

    mine = await _submission(tenant, klass, given, "Jan Kowalski")
    assert [storage.get(k) for k in mine.files] == [b"one"]
    assert mine.handed_in_at > first.handed_in_at
    assert len(await _grading_jobs(mine)) == 2


async def test_files_added_and_removed_within_the_quiet_time_change_nothing(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    tenant.upload(jan, "oops.jpg", b"wrong file")
    clock.advance(minutes=1)
    tenant.delete_file(jan, "oops.jpg")
    clock.advance(minutes=3)

    changed = await tenant.poll_handins()

    mine = await _submission(tenant, klass, given, "Jan Kowalski")
    assert (changed, mine.state, await _grading_jobs(mine)) == (0, "not_handed_in", [])


async def test_each_hand_in_is_only_the_files_of_that_students_folder(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    tenant.upload(users["Jan Kowalski"], "jan.jpg", b"jan")
    tenant.upload(users["Ewa Zielinska"], "ewa-1.jpg", b"ewa 1")
    tenant.upload(users["Ewa Zielinska"], "ewa-2.jpg", b"ewa 2")
    clock.advance(minutes=3)

    assert await tenant.poll_handins() == 2

    jan = await _submission(tenant, klass, given, "Jan Kowalski")
    ewa = await _submission(tenant, klass, given, "Ewa Zielinska")
    assert [storage.get(k) for k in jan.files] == [b"jan"]
    assert [storage.get(k) for k in ewa.files] == [b"ewa 1", b"ewa 2"]


async def test_two_assignments_keep_their_hand_ins_apart(tenant, gave, clock):
    klass, users, first = await _given(tenant, "Jan Kowalski")
    second = await tenant.give_assignment(klass.id, _spec(title="Potegi"), PDF)
    folders = [s.path for s in tenant.shared_with(users["Jan Kowalski"])]
    tenant.upload(users["Jan Kowalski"], "a.jpg", b"funkcje", folder=folders[0])
    clock.advance(minutes=3)

    await tenant.poll_handins()

    handed = [(await _submission(tenant, klass, a, "Jan Kowalski")).state for a in (first, second)]
    assert sorted(handed) == ["handed_in", "not_handed_in"]


async def test_at_close_students_who_have_not_handed_in_are_missing_and_folders_turn_read_only(
    tenant, gave, clock
):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    await _hand_in(tenant, clock, users["Jan Kowalski"], b"done")
    clock.now = given.close_at - timedelta(minutes=1)
    await tenant.poll_handins()
    assert {s.role for u in users.values() for s in tenant.shared_with(u)} == {"write"}

    clock.now = given.close_at
    await tenant.poll_handins()

    assert (await tenant.get_assignment(given.id)).state == "closed"
    assert (await _submission(tenant, klass, given, "Jan Kowalski")).state == "handed_in"
    assert (await _submission(tenant, klass, given, "Ewa Zielinska")).state == "missing"
    for user in users.values():
        assert [s.role for s in tenant.shared_with(user)] == ["read"]
        with pytest.raises(PermissionError):
            tenant.upload(user, "too-late.jpg", b"x")


async def test_the_close_settles_a_hand_in_still_in_its_quiet_time(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    clock.now = given.close_at - timedelta(minutes=1)
    tenant.upload(users["Jan Kowalski"], "a.jpg", b"just in time")
    clock.advance(minutes=1)

    await tenant.poll_handins()

    mine = await _submission(tenant, klass, given, "Jan Kowalski")
    assert (mine.state, mine.late) == ("handed_in", True)
    assert len(await _grading_jobs(mine)) == 1


async def test_files_uploaded_after_the_close_time_are_ignored(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    clock.now = given.close_at - timedelta(minutes=10)
    tenant.upload(users["Jan Kowalski"], "a.jpg", b"first")
    clock.now = given.close_at + timedelta(minutes=1)
    tenant.upload(users["Jan Kowalski"], "b.jpg", b"after the close")
    tenant.upload(users["Ewa Zielinska"], "c.jpg", b"after the close")
    clock.advance(minutes=5)

    await tenant.poll_handins()

    jan = await _submission(tenant, klass, given, "Jan Kowalski")
    assert [storage.get(k) for k in jan.files] == [b"first"]
    assert (await _submission(tenant, klass, given, "Ewa Zielinska")).state == "missing"
    clock.advance(hours=1)
    assert await tenant.poll_handins() == 0


async def test_a_student_who_left_before_being_reached_is_not_missing(tenant, gave, clock):
    klass, users = await make_class(tenant, "Jan Kowalski", "Ewa Zielinska")
    tenant.reject_chats(users["Ewa Zielinska"])
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    tenant.remove_member(klass.team_id, users["Ewa Zielinska"])
    tenant.remove_member(klass.team_id, users["Jan Kowalski"])
    await tenant.sync_roster(klass.id)

    clock.now = given.close_at
    await tenant.poll_handins()

    states = {
        s.display_name: (await _submission(tenant, klass, given, s.display_name)).state
        for s in await tenant.list_students(klass.id)
    }
    assert states == {"Jan Kowalski": "missing", "Ewa Zielinska": "not_handed_in"}


async def test_polling_waits_for_a_lapsed_sign_in(tenant, gave):
    await _given(tenant, "Jan Kowalski")
    tenant.lapse_sign_in()

    with pytest.raises(SignInRequired):
        await tenant.poll_handins()


async def test_the_poll_job_runs_the_poll_every_two_minutes(tenant, gave, clock, monkeypatch):
    _, users, _ = await _given(tenant, "Jan Kowalski")
    tenant.upload(users["Jan Kowalski"], "a.jpg", b"one")
    clock.advance(minutes=3)
    monkeypatch.setattr(teams, "backend", lambda: tenant)

    result = await handlers.poll_handins(Job(kind="teams.poll_handins", payload={}), ignore)

    assert result == {"changed": 1}
    assert ("teams.poll-handins", "rate(2 minutes)", "teams.poll_handins", {}) in _declared
