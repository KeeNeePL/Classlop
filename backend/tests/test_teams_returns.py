"""Returning Feedback to Students through the `teams` interface, against the real area over
FakeGraph and against FakeTeams. Grading's side is a stand-in at `grading.result`: the test says
what the result of a hand-in is, then tells `teams` it changed, as grading's job does."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from tenant import DUE, PDF, ignore, make_class
from tenant import spec as _spec

from classlop import grading, teams
from classlop.shared import storage
from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.shared.models import Job, Schedule
from classlop.teams import handlers, ids
from classlop.teams.lifecycle import schedule_names

COMMENT = "Dobra robota, popraw znak w zadaniu 2."
ATTACHMENT = "Ocena - Funkcje liniowe.pdf"


class Grader:
    """What `grading.result` says: set by `grade`, read back by `teams`."""

    def __init__(self):
        self.results: dict[tuple[uuid.UUID, object], grading.Result] = {}

    async def result(self, submission_id, handed_in_at):
        return self.results.get((submission_id, handed_in_at))

    def grade(self, submission, pdf=b"%PDF feedback one", **fields) -> grading.Result:
        """The result of the Submission's hand-in; a new PDF has a new key, as in grading."""
        who = ids.as_uuid(submission.id)
        key = f"grading/feedback/{who}/{uuid.uuid4()}.pdf"
        storage.put(key, pdf, "application/pdf")
        found = grading.Result(
            **{
                "submission_id": who,
                "handed_in_at": submission.handed_in_at,
                "status": "graded",
                "held_reasons": [],
                "spot_check_reasons": [],
                "comment": COMMENT,
                "pdf_key": key,
                "items": [],
                "approved_at": None,
            }
            | fields
        )
        self.results[who, submission.handed_in_at] = found
        return found


@pytest.fixture
def grader(monkeypatch) -> Grader:
    grader = Grader()
    monkeypatch.setattr(grading, "result", grader.result)
    return grader


def held(*items: int) -> list[grading.Reason]:
    return [grading.Reason(reason="nieczytelne", items=list(items) or [1])]


async def _given(tenant, *names, **changes):
    klass, users = await make_class(tenant, *names)
    return klass, users, await tenant.give_assignment(klass.id, _spec(**changes), PDF)


async def _submission(tenant, given, name):
    students = {s.display_name: s for s in await tenant.list_students(given.class_id)}
    found = await tenant.list_submissions(given.id)
    return next(s for s in found if s.student_id == students[name].id)


async def _hand_in(tenant, clock, given, users, name, *pages: bytes):
    """The Student uploads, three quiet minutes pass and the poll runs."""
    for number, page in enumerate(pages or (b"page",), 1):
        tenant.upload(users[name], f"strona-{number}-{len(page)}.jpg", page)
    clock.advance(minutes=3)
    await tenant.poll_handins()
    return await _submission(tenant, given, name)


async def _graded(tenant, grader, clock, given, users, name, **fields):
    """A hand-in, its result, and grading's word that the result is there."""
    mine = await _hand_in(tenant, clock, given, users, name)
    grader.grade(mine, **fields)
    await tenant.submission_graded(mine.id, mine.handed_in_at)
    return mine


async def _jobs(kind: str, assignment) -> list[Job]:
    async with sessions()() as session:
        found = await session.scalars(
            select(Job).where(
                Job.kind == kind,
                Job.payload["assignment_id"].astext == str(ids.as_uuid(assignment.id)),
            )
        )
    return list(found)


async def test_a_graded_submission_waits_for_the_due_time(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    notice = list(tenant.chat_messages(users["Jan Kowalski"]))

    await _graded(tenant, grader, clock, given, users, "Jan Kowalski")

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "graded"
    assert tenant.chat_messages(users["Jan Kowalski"]) == notice
    assert tenant.chat_files(users["Jan Kowalski"]) == []


async def test_at_the_due_time_graded_submissions_are_returned_in_the_one_to_one_chat(
    tenant, gave, clock, grader
):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    jan = users["Jan Kowalski"]
    await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    clock.now = given.due_at

    assert await tenant.return_graded(given.id) == 1

    mine = await _submission(tenant, given, "Jan Kowalski")
    assert mine.state == "returned"
    [_, message] = tenant.chat_messages(jan)
    assert COMMENT in message and "Funkcje liniowe" in message
    assert tenant.chat_files(jan) == [(ATTACHMENT, b"%PDF feedback one")]
    pdf = [s for s in tenant.shared_with(jan) if s.path.endswith(".pdf")]
    assert [s.role for s in pdf] == ["read"]
    assert (await _submission(tenant, given, "Ewa Zielinska")).state == "not_handed_in"
    assert len(tenant.chat_messages(users["Ewa Zielinska"])) == 1


async def test_return_turns_the_students_folder_read_only(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    assert {s.role for s in tenant.shared_with(jan)} == {"write"}
    clock.now = given.due_at

    await tenant.return_graded(given.id)

    assert {s.role for s in tenant.shared_with(jan)} == {"read"}
    with pytest.raises(PermissionError):
        tenant.upload(jan, "too-late.jpg", b"x")


async def test_a_returned_submission_is_no_longer_read_from_its_folder(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    clock.now = given.due_at
    await tenant.return_graded(given.id)
    before = await _submission(tenant, given, "Jan Kowalski")

    clock.advance(minutes=10)
    await tenant.poll_handins()

    assert await _submission(tenant, given, "Jan Kowalski") == before


async def test_a_late_submission_is_returned_as_soon_as_it_is_graded(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    clock.now = given.due_at + timedelta(hours=2)

    await _graded(tenant, grader, clock, given, users, "Jan Kowalski")

    mine = await _submission(tenant, given, "Jan Kowalski")
    assert (mine.state, mine.late) == ("returned", True)
    assert tenant.chat_files(users["Jan Kowalski"]) == [(ATTACHMENT, b"%PDF feedback one")]


async def test_a_graded_submission_graded_after_the_due_time_is_returned_on_grading(
    tenant, gave, clock, grader
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    mine = await _hand_in(tenant, clock, given, users, "Jan Kowalski")
    clock.now = given.due_at + timedelta(minutes=5)
    assert await tenant.return_graded(given.id) == 0

    grader.grade(mine)
    await tenant.submission_graded(mine.id, mine.handed_in_at)

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "returned"


async def test_a_held_submission_waits_for_the_teacher_even_after_the_due_time(
    tenant, gave, clock, grader
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    mine = await _graded(tenant, grader, clock, given, users, "Jan Kowalski", held_reasons=held())
    clock.now = given.due_at

    assert await tenant.return_graded(given.id) == 0
    assert (await _submission(tenant, given, "Jan Kowalski")).state == "graded"
    assert tenant.chat_files(jan) == []

    grader.grade(mine, held_reasons=held(), approved_at=clock.now)
    await tenant.submission_graded(mine.id, mine.handed_in_at)

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "returned"
    assert [name for name, _ in tenant.chat_files(jan)] == [ATTACHMENT]


async def test_a_held_late_submission_waits_for_the_teacher_too(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    clock.now = given.due_at + timedelta(hours=1)

    mine = await _graded(tenant, grader, clock, given, users, "Jan Kowalski", held_reasons=held())

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "graded"
    grader.grade(mine, held_reasons=held(), approved_at=clock.now)
    await tenant.submission_graded(mine.id, mine.handed_in_at)
    assert (await _submission(tenant, given, "Jan Kowalski")).state == "returned"


async def test_a_held_one_approved_before_the_due_time_is_returned_at_it(
    tenant, gave, clock, grader
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    mine = await _graded(tenant, grader, clock, given, users, "Jan Kowalski", held_reasons=held())

    grader.grade(mine, held_reasons=held(), approved_at=clock.now)
    await tenant.submission_graded(mine.id, mine.handed_in_at)
    assert (await _submission(tenant, given, "Jan Kowalski")).state == "graded"
    clock.now = given.due_at
    await tenant.return_graded(given.id)

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "returned"


async def test_a_failed_grading_is_not_returned(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    clock.now = given.due_at + timedelta(hours=1)

    await _graded(
        tenant,
        grader,
        clock,
        given,
        users,
        "Jan Kowalski",
        status="failed",
        pdf_key=None,
        held_reasons=held(),
    )

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "handed_in"
    assert tenant.chat_files(users["Jan Kowalski"]) == []


async def test_no_result_yet_changes_nothing(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    mine = await _hand_in(tenant, clock, given, users, "Jan Kowalski")

    await tenant.submission_graded(mine.id, mine.handed_in_at)

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "handed_in"


async def test_a_correction_after_return_is_a_new_message_with_the_new_pdf(
    tenant, gave, clock, grader
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    mine = await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    clock.now = given.due_at
    await tenant.return_graded(given.id)
    first = list(tenant.chat_messages(jan))

    grader.grade(mine, pdf=b"%PDF feedback two", comment="Poprawiona ocena zadania 2.")
    await tenant.submission_graded(mine.id, mine.handed_in_at)

    second = list(tenant.chat_messages(jan))
    assert second[: len(first)] == first
    assert len(second) == len(first) + 1
    assert "Poprawiona ocena zadania 2." in second[-1]
    assert tenant.chat_files(jan) == [
        (ATTACHMENT, b"%PDF feedback one"),
        (ATTACHMENT, b"%PDF feedback two"),
    ]
    assert len([s for s in tenant.shared_with(jan) if s.path.endswith(".pdf")]) == 2
    assert (await _submission(tenant, given, "Jan Kowalski")).state == "returned"


async def test_the_same_result_told_again_sends_nothing_more(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    mine = await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    clock.now = given.due_at
    await tenant.return_graded(given.id)
    sent = list(tenant.chat_messages(jan))

    await tenant.submission_graded(mine.id, mine.handed_in_at)
    await tenant.return_graded(given.id)

    assert tenant.chat_messages(jan) == sent


async def test_a_correction_that_holds_the_result_again_is_not_sent(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    mine = await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    clock.now = given.due_at
    await tenant.return_graded(given.id)
    sent = list(tenant.chat_messages(users["Jan Kowalski"]))

    grader.grade(mine, pdf=b"%PDF feedback two", held_reasons=held())
    await tenant.submission_graded(mine.id, mine.handed_in_at)

    assert tenant.chat_messages(users["Jan Kowalski"]) == sent


async def test_a_result_for_an_older_hand_in_is_ignored_and_the_new_one_is_returned(
    tenant, gave, clock, grader
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    old = await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    tenant.upload(jan, "dodatkowa.jpg", b"one more page")
    clock.advance(minutes=3)
    await tenant.poll_handins()
    new = await _submission(tenant, given, "Jan Kowalski")
    assert (new.state, new.handed_in_at > old.handed_in_at) == ("handed_in", True)

    await tenant.submission_graded(old.id, old.handed_in_at)
    assert (await _submission(tenant, given, "Jan Kowalski")).state == "handed_in"

    grader.grade(new, pdf=b"%PDF feedback new")
    await tenant.submission_graded(new.id, new.handed_in_at)
    clock.now = given.due_at
    await tenant.return_graded(given.id)

    assert tenant.chat_files(jan) == [(ATTACHMENT, b"%PDF feedback new")]


async def test_a_submission_that_is_not_owed_is_never_returned(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    clock.now = given.close_at
    await tenant.poll_handins()
    ewa = await _submission(tenant, given, "Ewa Zielinska")
    assert ewa.state == "missing"
    mine = await _submission(tenant, given, "Jan Kowalski")

    await tenant.submission_graded(ewa.id, clock.now)
    await tenant.submission_graded(mine.id, clock.now)

    assert (await _submission(tenant, given, "Ewa Zielinska")).state == "missing"
    assert tenant.chat_files(users["Ewa Zielinska"]) == []


async def test_an_unknown_submission_is_not_found(tenant, gave, clock, grader):
    with pytest.raises(LookupError):
        await tenant.submission_graded(ids.from_uuid(uuid.uuid4()), clock.now)


async def test_a_refused_chat_leaves_the_submission_graded_and_a_retry_sends_it_once(
    tenant, gave, clock, grader
):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    jan, ewa = users["Jan Kowalski"], users["Ewa Zielinska"]
    await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    await _graded(tenant, grader, clock, given, users, "Ewa Zielinska")
    clock.now = given.due_at
    tenant.reject_chats(jan)

    with pytest.raises(RuntimeError):
        await tenant.return_graded(given.id)

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "graded"
    assert (await _submission(tenant, given, "Ewa Zielinska")).state == "returned"
    assert len(tenant.chat_messages(jan)) == 1
    tenant.accept_chats(jan)
    await tenant.return_graded(given.id)
    await tenant.return_graded(given.id)

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "returned"
    assert len(tenant.chat_messages(jan)) == 2
    assert len(tenant.chat_messages(ewa)) == 2
    assert len([s for s in tenant.shared_with(jan) if s.path.endswith(".pdf")]) == 1


async def test_the_due_time_asks_grading_for_the_common_mistakes_once(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    clock.now = given.due_at

    await tenant.return_graded(given.id)
    await tenant.return_graded(given.id)

    [job] = await _jobs("grading.common_mistakes", given)
    assert job.payload == {"assignment_id": str(ids.as_uuid(given.id))}


async def test_giving_schedules_the_due_time_job_and_deleting_the_class_cancels_it(
    tenant, gave, clock
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    later = await tenant.give_assignment(
        klass.id, _spec(title="Potegi"), PDF, when=clock.now + timedelta(days=3)
    )

    for one in (given, later):
        name = f"teams.due:{one.id}"
        assert name in schedule_names(one.id)
        async with sessions()() as session:
            row = await session.get(Schedule, name)
        assert (row.kind, row.next_at, row.payload) == (
            "teams.assignment_due",
            DUE,
            {"assignment_id": one.id},
        )

    await tenant.delete_class(klass.id, "2A matematyka")

    async with sessions()() as session:
        assert await session.get(Schedule, f"teams.due:{given.id}") is None
        assert await session.get(Schedule, f"teams.due:{later.id}") is None


async def test_deleting_the_class_deletes_the_returned_pdfs_from_onedrive(
    tenant, gave, clock, grader
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    clock.now = given.due_at
    await tenant.return_graded(given.id)
    assert any(s.path.endswith(".pdf") for s in tenant.shared_with(jan))

    await tenant.delete_class(klass.id, "2A matematyka")

    assert tenant.shared_with(jan) == []


async def test_the_jobs_grading_and_the_schedule_enqueue_reach_the_area(
    tenant, gave, clock, grader, monkeypatch
):
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    klass, users, given = await _given(tenant, "Jan Kowalski")
    mine = await _hand_in(tenant, clock, given, users, "Jan Kowalski")
    grader.grade(mine)

    await handlers.submission_graded(
        Job(
            kind="teams.submission_graded",
            payload={
                "submission_id": str(ids.as_uuid(mine.id)),
                "handed_in_at": mine.handed_in_at.isoformat(),
            },
        ),
        ignore,
    )
    assert (await _submission(tenant, given, "Jan Kowalski")).state == "graded"
    clock.now = given.due_at
    await handlers.assignment_due(
        Job(kind="teams.assignment_due", payload={"assignment_id": given.id}), ignore
    )

    assert (await _submission(tenant, given, "Jan Kowalski")).state == "returned"


async def test_the_jobs_end_quietly_when_the_class_is_gone(
    tenant, gave, clock, grader, monkeypatch
):
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    klass, users, given = await _given(tenant, "Jan Kowalski")
    mine = await _hand_in(tenant, clock, given, users, "Jan Kowalski")
    await tenant.delete_class(klass.id, "2A matematyka")

    await handlers.submission_graded(
        Job(
            kind="teams.submission_graded",
            payload={
                "submission_id": str(ids.as_uuid(mine.id)),
                "handed_in_at": mine.handed_in_at.isoformat(),
            },
        ),
        ignore,
    )
    await handlers.assignment_due(
        Job(kind="teams.assignment_due", payload={"assignment_id": given.id}), ignore
    )


async def test_a_job_that_cannot_return_everything_fails_so_it_is_tried_again(
    tenant, gave, clock, grader, monkeypatch
):
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    klass, users, given = await _given(tenant, "Jan Kowalski")
    await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    clock.now = given.due_at
    tenant.reject_chats(users["Jan Kowalski"])

    with pytest.raises(RuntimeError):
        await handlers.assignment_due(
            Job(kind="teams.assignment_due", payload={"assignment_id": given.id}), ignore
        )


async def test_a_lapsed_sign_in_raises_what_parks_a_job(tenant, gave, clock, grader):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    mine = await _graded(tenant, grader, clock, given, users, "Jan Kowalski")
    clock.now = given.due_at
    tenant.lapse_sign_in()

    for call in (
        tenant.submission_graded(mine.id, mine.handed_in_at),
        tenant.return_graded(given.id),
    ):
        with pytest.raises(SignInRequired):
            await call
