"""Changing a Given Assignment through the `teams` interface, against the real area over FakeGraph
and against FakeTeams: moving its times, adding Students, excusing a Submission, deleting it."""

from datetime import timedelta

import pytest
from tenant import CLOSE, DUE, PDF, make_class
from tenant import spec as _spec

from classlop.teams import amendments


async def _given(tenant, *names, **changes):
    klass, users = await make_class(tenant, *names)
    given = await tenant.give_assignment(klass.id, _spec(**changes), PDF)
    return klass, users, given


async def test_moving_the_due_time_edits_the_post_and_replies_in_its_thread(tenant, gave):
    klass, _, given = await _given(tenant, "Jan Kowalski")
    later = DUE + timedelta(days=1)

    moved = await tenant.change_times(given.id, due_at=later)

    assert (moved.due_at, moved.close_at) == (later, CLOSE)
    assert await tenant.get_assignment(given.id) == moved
    [post] = tenant.channel_posts(klass.team_id)
    assert "16.09.2026 20:00" in post.html and "15.09.2026" not in post.html
    assert "Funkcje liniowe" in post.html
    assert post.files == {"Funkcje liniowe.pdf": PDF}
    [reply] = tenant.replies_to(post.id)
    assert "Zmiana terminu:" in reply and "16.09.2026 20:00" in reply


async def test_moving_only_the_close_time_changes_nothing_students_see(tenant, gave):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    [before] = tenant.channel_posts(klass.team_id)

    moved = await tenant.change_times(given.id, close_at=CLOSE + timedelta(days=1))

    assert (moved.due_at, moved.close_at) == (DUE, CLOSE + timedelta(days=1))
    [post] = tenant.channel_posts(klass.team_id)
    assert post.html == before.html
    assert tenant.replies_to(post.id) == []
    assert len(tenant.chat_messages(users["Jan Kowalski"])) == 1


async def test_a_scheduled_assignment_posts_the_new_due_time_without_a_reply(tenant, gave, clock):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    when = clock.now + timedelta(days=2)
    given = await tenant.give_assignment(klass.id, _spec(), PDF, when)
    later = DUE + timedelta(days=1)

    moved = await tenant.change_times(given.id, due_at=later)

    assert (moved.state, moved.due_at) == ("scheduled", later)
    assert tenant.channel_posts(klass.team_id) == []
    clock.now = when
    await tenant.publish_scheduled(given.id)
    [post] = tenant.channel_posts(klass.team_id)
    assert "16.09.2026 20:00" in post.html
    assert tenant.replies_to(post.id) == []


async def test_the_close_time_decides_when_the_poll_closes_the_assignment(tenant, gave, clock):
    _, _, given = await _given(tenant, "Jan Kowalski")
    await tenant.change_times(given.id, close_at=CLOSE + timedelta(days=1))

    clock.now = CLOSE + timedelta(hours=1)
    await tenant.poll_handins()
    assert (await tenant.get_assignment(given.id)).state == "open"
    clock.now = CLOSE + timedelta(days=1)
    await tenant.poll_handins()

    assert (await tenant.get_assignment(given.id)).state == "closed"


async def test_a_late_submission_is_late_against_the_due_time_as_it_now_stands(
    tenant, gave, clock
):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    clock.now = DUE + timedelta(hours=1)
    tenant.upload(users["Jan Kowalski"], "strona-1.jpg", b"page")
    clock.advance(minutes=3)
    await tenant.poll_handins()
    [late] = await tenant.list_submissions(given.id)
    assert (late.state, late.late) == ("handed_in", True)

    await tenant.change_times(given.id, due_at=DUE + timedelta(days=2))

    [on_time] = await tenant.list_submissions(given.id)
    assert on_time.late is False


async def test_the_reminder_and_the_return_follow_the_new_due_time(tenant, gave, monkeypatch):
    _, _, given = await _given(tenant, "Jan Kowalski")
    seen = []

    async def record(a):
        seen.append(a.due_at)

    monkeypatch.setattr(amendments, "reschedule_reminder", record)
    monkeypatch.setattr(amendments, "reschedule_return", record)

    await tenant.change_times(given.id, due_at=DUE + timedelta(days=1))

    assert seen == [DUE + timedelta(days=1)] * 2


@pytest.mark.parametrize(
    "bad",
    [
        {"close_at": DUE - timedelta(minutes=1)},
        {"due_at": CLOSE + timedelta(minutes=1)},
    ],
)
async def test_an_assignment_cannot_be_moved_to_close_before_it_is_due(tenant, gave, bad):
    klass, _, given = await _given(tenant, "Jan Kowalski")

    with pytest.raises(ValueError):
        await tenant.change_times(given.id, **bad)

    assert await tenant.get_assignment(given.id) == given
    [post] = tenant.channel_posts(klass.team_id)
    assert tenant.replies_to(post.id) == []


async def test_a_closed_assignment_keeps_its_times(tenant, gave, clock):
    _, _, given = await _given(tenant, "Jan Kowalski")
    clock.now = CLOSE
    await tenant.poll_handins()

    with pytest.raises(ValueError):
        await tenant.change_times(given.id, close_at=CLOSE + timedelta(days=1))


async def test_a_refused_correction_changes_nothing(tenant, gave):
    klass, _, given = await _given(tenant, "Jan Kowalski")
    tenant.reject_posts(klass.team_id)

    with pytest.raises(Exception):  # noqa: B017 - GraphError or the fake's refusal
        await tenant.change_times(given.id, due_at=DUE + timedelta(days=1))

    assert await tenant.get_assignment(given.id) == given
    [post] = tenant.channel_posts(klass.team_id)
    assert "15.09.2026" in post.html


async def _mine(tenant, given, klass, name):
    student = next(s for s in await tenant.list_students(klass.id) if s.display_name == name)
    return next(s for s in await tenant.list_submissions(given.id) if s.student_id == student.id)


async def test_a_submission_is_excused_with_a_private_reason(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    jan = await _mine(tenant, given, klass, "Jan Kowalski")

    excused = await tenant.excuse_submission(jan.id, "  choroba  ")

    assert (excused.state, excused.excused_reason) == ("excused", "choroba")
    assert await _mine(tenant, given, klass, "Jan Kowalski") == excused
    assert (await _mine(tenant, given, klass, "Ewa Zielinska")).state == "not_handed_in"
    assert len(tenant.chat_messages(users["Jan Kowalski"])) == 1  # only «Nowa praca»

    clock.now = CLOSE
    await tenant.poll_handins()
    assert (await _mine(tenant, given, klass, "Jan Kowalski")).state == "excused"
    assert (await _mine(tenant, given, klass, "Ewa Zielinska")).state == "missing"


async def test_the_reason_is_optional(tenant, gave):
    klass, _, given = await _given(tenant, "Jan Kowalski")
    jan = await _mine(tenant, given, klass, "Jan Kowalski")

    excused = await tenant.excuse_submission(jan.id, "  ")

    assert (excused.state, excused.excused_reason) == ("excused", None)


async def test_a_submission_can_be_excused_after_it_went_missing_or_was_handed_in(
    tenant, gave, clock
):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    tenant.upload(users["Ewa Zielinska"], "strona-1.jpg", b"page")
    clock.now = CLOSE
    await tenant.poll_handins()
    jan = await _mine(tenant, given, klass, "Jan Kowalski")
    ewa = await _mine(tenant, given, klass, "Ewa Zielinska")
    assert (jan.state, ewa.state) == ("missing", "handed_in")

    for submission in (jan, ewa):
        assert (await tenant.excuse_submission(submission.id)).state == "excused"


async def test_files_uploaded_after_the_excuse_are_ignored(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = await _mine(tenant, given, klass, "Jan Kowalski")
    await tenant.excuse_submission(jan.id)

    tenant.upload(users["Jan Kowalski"], "strona-1.jpg", b"page")
    clock.advance(minutes=5)
    await tenant.poll_handins()

    assert (await _mine(tenant, given, klass, "Jan Kowalski")).state == "excused"


async def test_a_student_joining_the_team_gets_an_open_whole_class_assignment(tenant, gave):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    ewa = tenant.add_member(klass.team_id, "Ewa Zielinska")

    await tenant.sync_roster(klass.id)

    [message] = tenant.chat_messages(ewa)
    assert "«Nowa praca»" in message and "Funkcje liniowe" in message
    [share] = tenant.shared_with(ewa)
    assert share.path == "Classlop/2A matematyka/Funkcje liniowe/Ewa Zielinska"
    assert share.role == "write" and share.url in message
    assert len(await tenant.list_submissions(given.id)) == 2
    assert len(tenant.chat_messages(users["Jan Kowalski"])) == 1


async def test_a_student_added_in_classlop_gets_the_assignment_too(tenant, gave):
    klass, _, given = await _given(tenant, "Jan Kowalski")
    ewa = tenant.add_user("Ewa Zielinska")

    await tenant.add_student(klass.id, ewa)

    assert len(tenant.chat_messages(ewa)) == 1
    assert len(await tenant.list_submissions(given.id)) == 2


async def test_syncing_again_sends_nothing_twice(tenant, gave):
    klass, _, given = await _given(tenant, "Jan Kowalski")
    ewa = tenant.add_member(klass.team_id, "Ewa Zielinska")

    await tenant.sync_roster(klass.id)
    await tenant.sync_roster(klass.id)

    assert len(tenant.chat_messages(ewa)) == 1
    assert len(tenant.shared_with(ewa)) == 1
    assert len(await tenant.list_submissions(given.id)) == 2


async def test_a_student_who_leaves_and_returns_is_not_told_again(tenant, gave):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = users["Jan Kowalski"]
    tenant.remove_member(klass.team_id, jan)
    await tenant.sync_roster(klass.id)
    tenant.add_member(klass.team_id, "Jan Kowalski", user_id=jan)

    await tenant.sync_roster(klass.id)

    assert len(tenant.chat_messages(jan)) == 1
    assert len(await tenant.list_submissions(given.id)) == 1


async def test_a_joiner_is_told_of_a_scheduled_assignment_when_it_is_posted(tenant, gave, clock):
    klass, _ = await make_class(tenant, "Jan Kowalski")
    when = clock.now + timedelta(days=2)
    given = await tenant.give_assignment(klass.id, _spec(), PDF, when)
    ewa = tenant.add_member(klass.team_id, "Ewa Zielinska")

    await tenant.sync_roster(klass.id)

    assert len(await tenant.list_submissions(given.id)) == 2
    assert tenant.chat_messages(ewa) == [] and tenant.shared_with(ewa) == []
    clock.now = when
    await tenant.publish_scheduled(given.id)
    assert len(tenant.chat_messages(ewa)) == 1


async def test_a_joiner_gets_neither_a_picked_nor_a_closed_assignment(tenant, gave, clock):
    klass, users = await make_class(tenant, "Jan Kowalski")
    jan = (await tenant.list_students(klass.id))[0]
    picked = await tenant.give_assignment(klass.id, _spec(student_ids=[jan.id]), PDF)
    closed = await tenant.give_assignment(klass.id, _spec(), PDF)
    clock.now = CLOSE
    await tenant.poll_handins()
    ewa = tenant.add_member(klass.team_id, "Ewa Zielinska")

    await tenant.sync_roster(klass.id)

    assert tenant.chat_messages(ewa) == [] and tenant.shared_with(ewa) == []
    assert len(await tenant.list_submissions(picked.id)) == 1
    assert len(await tenant.list_submissions(closed.id)) == 1


async def test_a_joiner_whose_message_fails_is_reached_by_the_retry(tenant, gave):
    klass, _, given = await _given(tenant, "Jan Kowalski")
    ewa = tenant.add_member(klass.team_id, "Ewa Zielinska")
    tenant.reject_chats(ewa)
    await tenant.sync_roster(klass.id)
    assert tenant.chat_messages(ewa) == []
    tenant.accept_chats(ewa)

    assert await tenant.deliver_assignment(given.id) == 0

    assert len(tenant.chat_messages(ewa)) == 1


async def test_students_are_added_to_a_given_picked_assignment(tenant, gave):
    klass, users = await make_class(tenant, "Jan Kowalski", "Ewa Zielinska")
    jan, ewa = (await tenant.list_students(klass.id))[:2]
    given = await tenant.give_assignment(klass.id, _spec(student_ids=[jan.id]), PDF)

    [added] = await tenant.add_recipients(given.id, [ewa.id])

    assert (added.student_id, added.state) == (ewa.id, "not_handed_in")
    assert added.folder_id and added.permission_id and added.notice_id
    assert len(tenant.chat_messages(users[ewa.display_name])) == 1
    assert [s.student_id for s in await tenant.list_submissions(given.id)] == [jan.id, ewa.id]
    assert (await tenant.get_assignment(given.id)).whole_class is False


async def test_adding_a_student_who_already_has_the_assignment_changes_nothing(tenant, gave):
    klass, users, given = await _given(tenant, "Jan Kowalski")
    jan = (await tenant.list_students(klass.id))[0]

    assert await tenant.add_recipients(given.id, [jan.id]) == []

    assert len(tenant.chat_messages(users["Jan Kowalski"])) == 1


async def test_only_current_students_of_the_class_are_added(tenant, gave, clock):
    klass, users, given = await _given(tenant, "Jan Kowalski", "Ewa Zielinska")
    ewa = next(s for s in await tenant.list_students(klass.id) if s.display_name == "Ewa Zielinska")
    tenant.remove_member(klass.team_id, users["Ewa Zielinska"])
    await tenant.sync_roster(klass.id)
    other_team = tenant.add_team("3B matematyka")
    tenant.add_member(other_team, "Adam Lis")
    adam = (await tenant.list_students((await tenant.link_team(other_team)).id))[0]

    for student in (ewa, adam):
        with pytest.raises(ValueError):
            await tenant.add_recipients(given.id, [student.id])

    clock.now = CLOSE
    await tenant.poll_handins()
    jan = next(s for s in await tenant.list_students(klass.id) if s.display_name == "Jan Kowalski")
    with pytest.raises(ValueError):
        await tenant.add_recipients(given.id, [jan.id])
