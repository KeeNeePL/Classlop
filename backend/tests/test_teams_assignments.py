"""Giving an Assignment through the `teams` interface, against the real area over FakeGraph and
against FakeTeams. Items are pinned by a recording stand-in for `items.give`."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from tenant import CLOSE, DUE, ITEMS, PDF, ignore
from tenant import make_class as _class
from tenant import spec as _spec

from classlop import items, teams
from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.shared.models import Job, Schedule
from classlop.shared.queue import MAX_RECEIVES
from classlop.teams import handlers, ids


async def test_giving_an_assignment_posts_it_in_general_with_the_items_pdf_and_the_due_time(
    tenant, gave
):
    klass, _ = await _class(tenant, "Jan Kowalski", "Ewa Zielinska")

    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    assert (given.state, given.title, given.due_at, given.close_at) == (
        "open",
        "Funkcje liniowe",
        DUE,
        CLOSE,
    )
    assert await tenant.get_assignment(given.id) == given
    [post] = tenant.channel_posts(klass.team_id)
    assert "Funkcje liniowe" in post.html
    assert "15.09.2026 20:00" in post.html
    assert "href" not in post.html
    assert post.files == {"Funkcje liniowe.pdf": PDF}


async def test_giving_freezes_the_items_when_the_post_is_accepted(tenant, gave, clock):
    klass, _ = await _class(tenant, "Jan Kowalski")

    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    assert given.given_at == clock.now
    assert given.item_versions == [uuid.UUID(int=101), uuid.UUID(int=102)]
    assert gave == [(ITEMS, ids.as_uuid(given.id), ids.as_uuid(klass.id), clock.now)]


async def test_each_recipient_gets_a_folder_shared_to_them_only_with_write_access(tenant, gave):
    klass, users = await _class(tenant, "Jan Kowalski", "Ewa Zielinska")

    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    base = "Classlop/2A matematyka/Funkcje liniowe"
    jan, ewa = (tenant.shared_with(users[n]) for n in ("Jan Kowalski", "Ewa Zielinska"))
    assert [(s.path, s.role) for s in jan] == [(f"{base}/Jan Kowalski", "write")]
    assert [(s.path, s.role) for s in ewa] == [(f"{base}/Ewa Zielinska", "write")]
    assert tenant.invitation_emails() == 0
    submissions = {s.student_id: s for s in await tenant.list_submissions(given.id)}
    students = {s.display_name: s for s in await tenant.list_students(klass.id)}
    assert len(submissions) == 2
    for name, shares in (("Jan Kowalski", jan), ("Ewa Zielinska", ewa)):
        submission = submissions[students[name].id]
        assert (submission.state, submission.folder_url) == ("not_handed_in", shares[0].url)
        assert submission.folder_id and submission.permission_id


async def test_each_recipient_gets_a_nowa_praca_message_with_their_folder_link(tenant, gave):
    klass, users = await _class(tenant, "Jan Kowalski", "Ewa Zielinska")

    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    [jan_message] = tenant.chat_messages(users["Jan Kowalski"])
    [ewa_message] = tenant.chat_messages(users["Ewa Zielinska"])
    jan_url = tenant.shared_with(users["Jan Kowalski"])[0].url
    ewa_url = tenant.shared_with(users["Ewa Zielinska"])[0].url
    assert "«Nowa praca»" in jan_message and "Funkcje liniowe" in jan_message
    assert "15.09.2026 20:00" in jan_message
    assert "przeglądarce" in jan_message
    assert jan_url in jan_message and ewa_url not in jan_message
    assert ewa_url in ewa_message and jan_url not in ewa_message
    submissions = await tenant.list_submissions(given.id)
    assert all(s.chat_id and s.notice_id for s in submissions)


async def test_a_message_that_fails_is_retried_for_that_student_only(tenant, gave):
    klass, users = await _class(tenant, "Jan Kowalski", "Ewa Zielinska")
    jan, ewa = users["Jan Kowalski"], users["Ewa Zielinska"]
    tenant.reject_chats(jan)

    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    assert given.state == "open"
    assert (len(tenant.chat_messages(jan)), len(tenant.chat_messages(ewa))) == (0, 1)
    async with sessions()() as session:
        retries = await session.scalars(
            select(Job).where(
                Job.kind == "teams.deliver_assignment",
                Job.payload["assignment_id"].astext == given.id,
            )
        )
    assert len(retries.all()) == 1
    assert await tenant.deliver_assignment(given.id) == 1
    tenant.accept_chats(jan)

    assert await tenant.deliver_assignment(given.id) == 0
    assert (len(tenant.chat_messages(jan)), len(tenant.chat_messages(ewa))) == (1, 1)
    assert len(tenant.shared_with(jan)) == 1


async def test_the_retry_job_fails_until_every_student_has_their_message(tenant, gave, monkeypatch):
    klass, users = await _class(tenant, "Jan Kowalski")
    tenant.reject_chats(users["Jan Kowalski"])
    given = await tenant.give_assignment(klass.id, _spec(), PDF)
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    job = Job(kind="teams.deliver_assignment", payload={"assignment_id": given.id})

    with pytest.raises(RuntimeError):
        await handlers.deliver_assignment(job, ignore)
    tenant.accept_chats(users["Jan Kowalski"])
    await handlers.deliver_assignment(job, ignore)

    assert len(tenant.chat_messages(users["Jan Kowalski"])) == 1


async def _scheduled(tenant, clock, *names, **spec):
    klass, users = await _class(tenant, *names)
    when = clock.now + timedelta(days=2)
    given = await tenant.give_assignment(klass.id, _spec(**spec), PDF, when)
    return klass, users, given, when


def _publish_job(given, **fields) -> Job:
    fields = {"attempts": 1, **fields}
    return Job(kind="teams.give_assignment", payload={"assignment_id": given.id}, **fields)


async def test_scheduling_makes_the_assignment_given_at_once_and_posts_nothing_yet(
    tenant, gave, clock
):
    klass, users, given, when = await _scheduled(tenant, clock, "Jan Kowalski")

    assert (given.state, given.publish_at, given.given_at) == ("scheduled", when, clock.now)
    assert given.item_versions == [uuid.UUID(int=101), uuid.UUID(int=102)]
    assert len(gave) == 1
    assert tenant.channel_posts(klass.team_id) == []
    assert tenant.shared_with(users["Jan Kowalski"]) == []
    assert tenant.chat_messages(users["Jan Kowalski"]) == []
    async with sessions()() as session:
        row = await session.get(Schedule, f"teams.give:{given.id}")
    assert (row.kind, row.every_seconds, row.next_at) == ("teams.give_assignment", None, when)
    assert row.payload == {"assignment_id": given.id}


async def test_at_the_scheduled_time_the_post_opens_the_assignment(
    tenant, gave, clock, monkeypatch
):
    klass, users, given, when = await _scheduled(tenant, clock, "Jan Kowalski")
    clock.now = when
    monkeypatch.setattr(teams, "backend", lambda: tenant)

    await handlers.give_assignment(_publish_job(given), ignore)

    opened = await tenant.get_assignment(given.id)
    assert (opened.state, opened.given_at, opened.give_failed_at) == ("open", given.given_at, None)
    assert [p.files for p in tenant.channel_posts(klass.team_id)] == [{"Funkcje liniowe.pdf": PDF}]
    assert len(tenant.chat_messages(users["Jan Kowalski"])) == 1
    assert len(gave) == 1


async def test_a_scheduled_post_that_still_fails_returns_to_draft_with_a_signal(
    tenant, gave, clock, monkeypatch
):
    klass, _, given, when = await _scheduled(tenant, clock, "Jan Kowalski")
    clock.now = when
    tenant.reject_posts(klass.team_id)
    monkeypatch.setattr(teams, "backend", lambda: tenant)

    with pytest.raises(Exception):  # noqa: B017 - the job is tried again
        await handlers.give_assignment(_publish_job(given, attempts=1), ignore)
    assert (await tenant.get_assignment(given.id)).state == "scheduled"
    await handlers.give_assignment(_publish_job(given, attempts=MAX_RECEIVES), ignore)

    draft = await tenant.get_assignment(given.id)
    assert (draft.state, draft.give_failed_at, draft.publish_at) == ("draft", clock.now, None)
    assert [a.id for a in await tenant.list_failed_gives()] == [given.id]
    assert tenant.channel_posts(klass.team_id) == []


async def test_a_draft_that_failed_to_be_given_can_be_given_again(tenant, gave, clock, monkeypatch):
    klass, users, given, when = await _scheduled(tenant, clock, "Jan Kowalski")
    clock.now = when
    tenant.reject_posts(klass.team_id)
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    await handlers.give_assignment(_publish_job(given, attempts=MAX_RECEIVES), ignore)
    tenant.accept_posts(klass.team_id)

    again = await tenant.give_again(given.id)

    assert (again.state, again.give_failed_at) == ("open", None)
    assert await tenant.list_failed_gives() == []
    assert len(tenant.channel_posts(klass.team_id)) == 1
    assert len(tenant.chat_messages(users["Jan Kowalski"])) == 1
    assert len(gave) == 1


async def test_a_draft_can_be_given_again_at_a_later_time(tenant, gave, clock, monkeypatch):
    klass, _, given, when = await _scheduled(tenant, clock, "Jan Kowalski")
    clock.now = when
    tenant.reject_posts(klass.team_id)
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    await handlers.give_assignment(_publish_job(given, attempts=MAX_RECEIVES), ignore)
    tenant.accept_posts(klass.team_id)

    later = await tenant.give_again(given.id, clock.now + timedelta(hours=3))

    assert (later.state, later.publish_at) == ("scheduled", clock.now + timedelta(hours=3))


async def test_only_a_draft_can_be_given_again(tenant, gave, clock):
    _, _, given, _ = await _scheduled(tenant, clock, "Jan Kowalski")

    with pytest.raises(ValueError):
        await tenant.give_again(given.id)


async def test_a_whole_class_assignment_reaches_current_students_only(tenant, gave):
    klass, users = await _class(tenant, "Jan Kowalski", "Ewa Zielinska")
    tenant.remove_member(klass.team_id, users["Ewa Zielinska"])
    await tenant.sync_roster(klass.id)

    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    assert given.whole_class
    assert [s.student_id for s in await tenant.list_submissions(given.id)] == [
        s.id for s in await tenant.list_students(klass.id) if not s.former_since
    ]
    assert tenant.shared_with(users["Ewa Zielinska"]) == []


async def test_a_picked_assignment_reaches_the_picked_students_only(tenant, gave):
    klass, users = await _class(tenant, "Jan Kowalski", "Ewa Zielinska")
    ewa = next(s for s in await tenant.list_students(klass.id) if s.display_name == "Ewa Zielinska")

    given = await tenant.give_assignment(klass.id, _spec(student_ids=[ewa.id]), PDF)

    assert not given.whole_class
    assert [s.student_id for s in await tenant.list_submissions(given.id)] == [ewa.id]
    assert tenant.shared_with(users["Jan Kowalski"]) == []
    assert len(tenant.chat_messages(users["Ewa Zielinska"])) == 1
    assert len(tenant.channel_posts(klass.team_id)) == 1


async def test_students_of_another_class_cannot_be_picked(tenant, gave):
    klass, _ = await _class(tenant, "Jan Kowalski")
    other_team = tenant.add_team("3B matematyka")
    tenant.add_member(other_team, "Adam Lis")
    other = await tenant.link_team(other_team)
    adam = (await tenant.list_students(other.id))[0]

    with pytest.raises(ValueError):
        await tenant.give_assignment(klass.id, _spec(student_ids=[adam.id]), PDF)

    assert gave == []


async def test_the_roster_is_synced_before_giving(tenant, gave):
    klass, _ = await _class(tenant, "Jan Kowalski")
    ewa = tenant.add_member(klass.team_id, "Ewa Zielinska")

    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    assert len(await tenant.list_submissions(given.id)) == 2
    assert len(tenant.chat_messages(ewa)) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"title": "  "},
        {"item_ids": []},
        {"close_at": DUE - timedelta(minutes=1)},
    ],
)
async def test_an_assignment_must_have_a_title_items_and_a_close_after_the_due_time(
    tenant, gave, bad
):
    klass, _ = await _class(tenant, "Jan Kowalski")

    with pytest.raises(ValueError):
        await tenant.give_assignment(klass.id, _spec(**bad), PDF)

    assert await tenant.list_assignments(klass.id) == []


async def test_an_assignment_is_scheduled_for_a_time_to_come(tenant, gave, clock):
    klass, _ = await _class(tenant, "Jan Kowalski")

    with pytest.raises(ValueError):
        await tenant.give_assignment(klass.id, _spec(), PDF, clock.now)

    assert await tenant.list_assignments(klass.id) == []


async def test_the_reminder_choice_and_type_are_kept(tenant, gave):
    klass, _ = await _class(tenant, "Jan Kowalski")

    quiz = await tenant.give_assignment(klass.id, _spec(type="quiz", reminder_on=False), PDF)

    assert (quiz.type, quiz.reminder_on) == ("quiz", False)
    assert await tenant.list_assignments(klass.id) == [quiz]


async def test_names_with_characters_onedrive_refuses_still_make_folders(tenant, gave):
    klass, users = await _class(tenant, "Jan Kowalski")

    await tenant.give_assignment(klass.id, _spec(title="Zestaw 3/4: funkcje?"), PDF)

    [share] = tenant.shared_with(users["Jan Kowalski"])
    assert share.path == "Classlop/2A matematyka/Zestaw 3 4 funkcje/Jan Kowalski"
    [post] = tenant.channel_posts(klass.team_id)
    assert list(post.files) == ["Zestaw 3 4 funkcje.pdf"]


async def test_two_assignments_with_one_title_keep_their_folders_apart(tenant, gave):
    klass, users = await _class(tenant, "Jan Kowalski")

    await tenant.give_assignment(klass.id, _spec(), PDF)
    await tenant.give_assignment(klass.id, _spec(), PDF)

    paths = [s.path for s in tenant.shared_with(users["Jan Kowalski"])]
    assert len(set(paths)) == 2
    assert all(p.startswith("Classlop/2A matematyka/") for p in paths)
    assert len(tenant.channel_posts(klass.team_id)) == 2


async def test_giving_waits_for_a_lapsed_sign_in(tenant, gave, clock):
    klass, users = await _class(tenant, "Jan Kowalski")
    tenant.reject_chats(users["Jan Kowalski"])
    unreached = await tenant.give_assignment(klass.id, _spec(), PDF)
    scheduled = await tenant.give_assignment(klass.id, _spec(), PDF, clock.now + timedelta(days=1))
    tenant.lapse_sign_in()

    for call in (
        tenant.give_assignment(klass.id, _spec(), PDF),
        tenant.give_assignment(klass.id, _spec(), PDF, clock.now + timedelta(days=1)),
        tenant.deliver_assignment(unreached.id),
        tenant.publish_scheduled(scheduled.id),
    ):
        with pytest.raises(SignInRequired):
            await call


async def test_same_named_students_get_folders_of_their_own(tenant, gave):
    klass, users = await _class(tenant, "Jan Kowalski")
    other = tenant.add_member(klass.team_id, "Jan Kowalski")

    await tenant.give_assignment(klass.id, _spec(), PDF)

    paths = [tenant.shared_with(u)[0].path for u in (users["Jan Kowalski"], other)]
    assert len(set(paths)) == 2


async def test_an_assignment_whose_post_is_refused_is_not_given(tenant, gave):
    klass, _ = await _class(tenant, "Jan Kowalski")
    tenant.reject_posts(klass.team_id)

    with pytest.raises(Exception):  # noqa: B017 - GraphError or the fake's refusal
        await tenant.give_assignment(klass.id, _spec(), PDF)

    assert gave == []
    assert await tenant.list_assignments(klass.id) == []
    assert tenant.channel_posts(klass.team_id) == []


async def test_a_failure_after_the_post_is_accepted_is_finished_by_a_retry_job(
    tenant, gave, monkeypatch
):
    klass, users = await _class(tenant, "Jan Kowalski")
    working = items.give
    broken = True

    async def give(*args):
        if broken:
            raise RuntimeError("the Items are unreachable")
        return await working(*args)

    monkeypatch.setattr(items, "give", give)

    given = await tenant.give_assignment(klass.id, _spec(), PDF)

    assert (given.state, given.item_versions) == ("open", [])
    assert len(tenant.channel_posts(klass.team_id)) == 1
    async with sessions()() as session:
        retries = await session.scalars(
            select(Job).where(
                Job.kind == "teams.give_assignment",
                Job.payload["assignment_id"].astext == given.id,
            )
        )
    assert len(retries.all()) == 1
    broken = False
    monkeypatch.setattr(teams, "backend", lambda: tenant)
    await handlers.give_assignment(_publish_job(given), ignore)

    finished = await tenant.get_assignment(given.id)
    assert finished.item_versions == [uuid.UUID(int=101), uuid.UUID(int=102)]
    assert len(tenant.channel_posts(klass.team_id)) == 1
    assert len(tenant.chat_messages(users["Jan Kowalski"])) == 1
