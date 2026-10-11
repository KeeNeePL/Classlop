"""Nowa praca over HTTP: the form with the bank's stock, picking and swapping Items, and giving
the Assignment through FakeTeams. The bank is in memory; giving needs no database."""

import uuid
from datetime import UTC, datetime, timedelta

import pypdfium2 as pdfium
import pytest
from e2e_app import create
from fake_bank import THEN, InMemoryBank
from fake_work import CLASS_NAME, STUDENTS, Offline, invented_class
from fastapi.testclient import TestClient

from classlop import teams
from classlop.dashboard import bank, home
from classlop.teams.fake import FakeTeams
from classlop.teams.ids import as_uuid

OPEN_MEDIUM_III = uuid.UUID(int=1001)  # lo2024:III, medium, open


class Screen:
    def __init__(
        self, web: TestClient, fake: FakeTeams, items: InMemoryBank, offline: Offline, class_id: str
    ):
        self.web, self.fake, self.bank = web, fake, items
        self.offline, self.class_id = offline, class_id

    def get(self, path: str):
        return self.web.get(f"/api/classes/{self.class_id}/{path}")

    def post(self, path: str, body: dict):
        return self.web.post(f"/api/classes/{self.class_id}/{path}", json=body)

    def got(self, *item_ids: uuid.UUID) -> None:
        """The Class has been given these Items before."""
        for i in item_ids:
            self.bank.classes_used[i].add(as_uuid(self.class_id))


@pytest.fixture
async def screen(monkeypatch):
    app = create()
    # The real source of failed gives, over FakeTeams.
    del app.dependency_overrides[home.failed_gives]
    items = app.dependency_overrides[bank.backend]()
    fake = FakeTeams()
    monkeypatch.setattr(teams, "_backend", fake)
    offline = Offline(items)
    for module, name, replacement in offline.patches():
        monkeypatch.setattr(module, name, replacement)
    klass = await invented_class(fake)
    return Screen(TestClient(app), fake, items, offline, klass.id)


async def test_the_form_has_the_students_and_the_stock_with_and_without_what_the_class_got(
    screen,
):
    screen.got(OPEN_MEDIUM_III)

    form = screen.get("new-work").json()

    assert form["class_name"] == CLASS_NAME
    assert sorted(s["name"] for s in form["students"]) == sorted(STUDENTS)
    assert form["sections"][0]["id"] == "lo2024:I"
    stock = {(c["section"], c["difficulty"]): c["count"] for c in form["stock"]}
    unused = {(c["section"], c["difficulty"]): c["count"] for c in form["unused"]}
    # Retired Items are not stock.
    assert stock[("lo2024:II", "easy")] == 1
    assert stock[("lo2024:III", "medium")] == 1
    assert ("lo2024:III", "medium") not in unused
    assert unused[("lo2024:III", "hard")] == 1


def line(section: str, difficulty: str, count: int) -> dict:
    return {"section": section, "difficulty": difficulty, "count": count}


async def test_a_pick_fills_the_lines_and_names_what_the_bank_lacks(screen):
    picked = screen.post(
        "new-work/pick",
        {"lines": [line("lo2024:III", "hard", 1), line("lo2024:II", "easy", 3)]},
    ).json()

    assert [(e["section"], e["difficulty"]) for e in picked["entries"]] == [
        ("lo2024:III", "hard"),
        ("lo2024:II", "easy"),
    ]
    assert picked["entries"][0]["item"]["version"]["text"] == "Ile pierwiastków ma $x^2 + 1$?"
    assert picked["shortfalls"] == [
        {"section": "lo2024:II", "difficulty": "easy", "wanted": 3, "got": 1}
    ]


async def test_an_item_is_picked_once_for_the_whole_preview(screen):
    picked = screen.post(
        "new-work/pick",
        {"lines": [line("lo2024:III", "hard", 1), line("lo2024:III", "hard", 1)]},
    ).json()

    assert len(picked["entries"]) == 1
    assert picked["shortfalls"][0]["got"] == 0


async def test_what_the_class_got_is_skipped_unless_the_teacher_allows_it(screen):
    screen.got(uuid.UUID(int=1008))
    lines = [line("lo2024:III", "hard", 1)]

    skipped = screen.post("new-work/pick", {"lines": lines}).json()
    allowed = screen.post("new-work/pick", {"lines": lines, "allow_reuse": True}).json()

    assert skipped["entries"] == []
    assert len(allowed["entries"]) == 1 and allowed["shortfalls"] == []


async def test_a_pick_of_a_section_the_curriculum_lacks_is_refused(screen):
    assert (
        screen.post("new-work/pick", {"lines": [line("lo2024:XX", "hard", 1)]}).status_code == 422
    )


def another_hard_equation(screen) -> uuid.UUID:
    """A second Item at lo2024:III, hard, in the bank."""
    original = screen.bank.items[uuid.UUID(int=1008)]
    spare = original.model_copy(update={"id": uuid.UUID(int=1100), "created_at": THEN})
    screen.bank.items[spare.id] = spare
    screen.bank.classes_used[spare.id] = set()
    return spare.id


async def test_a_swap_gives_another_item_of_the_same_cell(screen):
    spare = another_hard_equation(screen)

    swapped = screen.post(
        "new-work/swap",
        {"section": "lo2024:III", "difficulty": "hard", "exclude": [str(uuid.UUID(int=1008))]},
    ).json()

    assert swapped["item"]["id"] == str(spare)


async def test_a_swap_with_no_other_item_left_returns_none(screen):
    swapped = screen.post(
        "new-work/swap",
        {"section": "lo2024:III", "difficulty": "hard", "exclude": [str(uuid.UUID(int=1008))]},
    ).json()

    assert swapped == {"item": None}


DUE = datetime.now(UTC).replace(microsecond=0) + timedelta(days=3)
OPEN_ITEM = uuid.UUID(int=1001)
CLOSED_ITEM = uuid.UUID(int=1002)


def give_body(**changes) -> dict:
    return {
        "title": "Równania kwadratowe",
        "type": "homework",
        "item_ids": [str(OPEN_ITEM), str(CLOSED_ITEM)],
        "student_ids": None,
        "reminder_on": True,
        "due_at": DUE.isoformat(),
        **changes,
    }


def pdf_text(pdf: bytes) -> str:
    document = pdfium.PdfDocument(pdf)
    return "\n".join(page.get_textpage().get_text_range() for page in document)


async def test_giving_now_posts_the_items_pdf_and_reaches_every_student(screen):
    response = screen.post("assignments", give_body())

    assert response.status_code == 200
    (given,) = await screen.fake.list_assignments(screen.class_id)
    assert response.json() == {"id": given.id, "state": "open"}
    assert (given.title, given.type, given.reminder_on, given.whole_class) == (
        "Równania kwadratowe",
        "homework",
        True,
        True,
    )
    assert given.close_at == DUE + timedelta(days=7)
    team = (await teams.get_class(screen.class_id)).team_id
    (post,) = screen.fake.channel_posts(team)
    text = pdf_text(post.files["Równania kwadratowe.pdf"])
    # The Items in the order picked, with their points.
    assert text.index("1. Rozwiąż równanie") < text.index("2. Wartość wyrażenia")
    assert "(2 pkt)" in text and "A) " in text
    assert all(
        screen.fake.chat_messages(u)
        for u in (s.user_id for s in await teams.list_students(screen.class_id))
    )
    # `items.give` pinned the Items, so the Class has now got them.
    assert as_uuid(screen.class_id) in screen.bank.classes_used[OPEN_ITEM]


async def test_a_quiz_closes_five_minutes_after_it_is_due(screen):
    screen.post("assignments", give_body(type="quiz"))

    (given,) = await screen.fake.list_assignments(screen.class_id)
    assert given.close_at == DUE + timedelta(minutes=5)


async def test_giving_to_picked_students_reaches_only_them(screen):
    first, *_ = await teams.list_students(screen.class_id)

    screen.post("assignments", give_body(student_ids=[first.id]))

    (given,) = await screen.fake.list_assignments(screen.class_id)
    assert not given.whole_class
    reached = [
        s
        for s in await teams.list_students(screen.class_id)
        if screen.fake.chat_messages(s.user_id)
    ]
    assert [s.id for s in reached] == [first.id]


async def test_giving_at_a_time_schedules_it_at_once(screen):
    at = DUE - timedelta(days=1)

    response = screen.post("assignments", give_body(publish_at=at.isoformat()))

    assert response.json()["state"] == "scheduled"
    assert list(screen.offline.scheduled.values())[0] == at
    team = (await teams.get_class(screen.class_id)).team_id
    assert screen.fake.channel_posts(team) == []


async def test_nothing_is_given_while_the_preview_is_empty(screen):
    response = screen.post("assignments", give_body(item_ids=[]))

    assert response.status_code == 422
    assert await screen.fake.list_assignments(screen.class_id) == []


async def test_an_item_that_cannot_be_typeset_stops_the_giving(screen):
    screen.bank.items[OPEN_ITEM].version.text = "Oblicz $x"

    response = screen.post("assignments", give_body())

    assert response.status_code == 422
    assert await screen.fake.list_assignments(screen.class_id) == []


async def test_a_post_teams_refuses_leaves_nothing_given(screen):
    screen.fake.reject_posts((await teams.get_class(screen.class_id)).team_id)

    response = screen.post("assignments", give_body())

    assert response.status_code == 502
    assert await screen.fake.list_assignments(screen.class_id) == []


async def test_a_scheduled_give_that_fails_shows_on_do_zrobienia(screen):
    given = screen.post(
        "assignments", give_body(publish_at=(DUE - timedelta(days=1)).isoformat())
    ).json()
    screen.fake.reject_posts((await teams.get_class(screen.class_id)).team_id)

    await teams.publish_scheduled(given["id"], last_try=True)

    entries = screen.web.get("/api/home").json()["entries"]
    (failed,) = [e for e in entries if e["link"].endswith(given["id"])]
    assert failed["kind"] == "give_failed"
    assert failed["title"] == "Nie udało się wydać pracy «Równania kwadratowe»"
    assert CLASS_NAME in failed["detail"]
