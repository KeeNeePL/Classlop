"""The Bank zadań over the real areas: `items` search and edits through the stand-ins from
compose, usage joined from `grading`, with `teams` answering for Assignments and Classes."""

import asyncio
import os
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from opensearchpy import NotFoundError
from test_grading_averages import submit
from test_items import closed, fake_embeddings, indexed, marker, open_content  # noqa: F401

from classlop import items, teams
from classlop.dashboard import auth, bank
from classlop.dashboard.app import create_app
from classlop.items import CurriculumTopic, Tags, index
from classlop.shared import queue, search
from classlop.shared.migrate import migrate
from classlop.shared.settings import get_settings
from classlop.teams.ids import as_uuid, from_uuid

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
async def stack():
    try:
        await asyncio.to_thread(migrate)
        await asyncio.to_thread(queue.url)
        await search.ping()
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d")
    index._created.clear()
    yield
    with suppress(NotFoundError):
        await search.client().indices.delete(index=get_settings().items_index)
    index._created.clear()


class Retagger:
    """Always says the text is about functions and hard."""

    async def tag(self, text: str) -> Tags:
        return Tags(
            difficulty="hard",
            curriculum_topics=[CurriculumTopic(id="lo2024:V.1", name="Funkcje")],
            general_requirements=["III"],
        )


@pytest.fixture
def web(fake_embeddings):  # noqa: F811
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    app.dependency_overrides[bank.backend] = lambda: bank.ItemsBank(tagger=Retagger())
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def call(web: AsyncClient, method: str, url: str, **kw):
    return await web.request(method, url, **kw)


async def test_usage_has_each_giving_with_its_assignment_class_and_average(web, monkeypatch):
    item_id = await items.create_item(closed(), origin="chat")
    other = await items.create_item(closed(text="Inne zadanie"), origin="chat")
    quiz, exam, gone = (uuid.uuid4() for _ in range(3))
    class_a, class_b = uuid.uuid4(), uuid.uuid4()
    await items.give([item_id, other], quiz, class_a, NOW)
    await items.give([item_id], exam, class_b, NOW.replace(day=8))
    await items.give([item_id], gone, class_b, NOW.replace(day=9))
    await submit(quiz, {item_id: (2, 2), other: (0, 2)})
    await submit(quiz, {item_id: (1, 2), other: (0, 2)})
    await submit(exam, {item_id: (0, 2)}, held=True)

    titles = {from_uuid(quiz): "Kartkówka", from_uuid(exam): "Sprawdzian"}
    names = {from_uuid(class_a): "1A", from_uuid(class_b): "2C"}

    async def get_assignment(id: str):
        if id not in titles:
            raise LookupError(id)
        return SimpleNamespace(title=titles[id])

    async def get_class(id: str):
        return SimpleNamespace(name=names[id])

    monkeypatch.setattr(teams, "get_assignment", get_assignment)
    monkeypatch.setattr(teams, "get_class", get_class)

    detail = (await call(web, "GET", f"/api/bank/items/{item_id}")).json()

    assert [
        (u["assignment_id"], u["title"], u["class_name"], u["average"]) for u in detail["usage"]
    ] == [
        (from_uuid(quiz), "Kartkówka", "1A", 0.75),
        (from_uuid(exam), "Sprawdzian", "2C", None),  # the one Submission is Held
        (from_uuid(gone), None, "2C", None),
    ]
    (twin,) = (await call(web, "GET", f"/api/bank/items/{other}")).json()["usage"]
    assert twin["average"] == 0.0


async def test_the_classes_to_filter_by_are_the_teams_classes(web, monkeypatch):
    ulid = from_uuid(uuid.uuid4())

    async def list_classes():
        return [SimpleNamespace(id=ulid, name="3B")]

    monkeypatch.setattr(teams, "list_classes", list_classes)

    filters = (await call(web, "GET", "/api/bank/filters")).json()

    assert filters["classes"] == [{"id": str(as_uuid(ulid)), "name": "3B"}]


async def test_search_filters_and_retiring_go_through_the_item_bank(web):
    word = marker()
    keep = await items.create_item(closed(text=f"{word} jedno"), origin="chat")
    drop = await items.create_item(open_content(text=f"{word} drugie"), origin="chat")
    flagged = await items.create_item(
        closed(text=f"{word} trzecie"), origin="chat", flag_reason="brak wzorca"
    )
    await indexed()

    async def ids(**params) -> set[str]:
        page = (await call(web, "GET", "/api/bank/items", params={"q": word} | params)).json()
        # Text and k-NN both run, so other tests' Items may come back too; compare ours.
        return {i["id"] for i in page["items"]} & {str(keep), str(drop), str(flagged)}

    assert await ids() == {str(keep), str(drop), str(flagged)}
    assert await ids(flagged=True) == {str(flagged)}
    assert await ids(item_format="open") == {str(drop)}

    assert (await call(web, "POST", f"/api/bank/items/{drop}/retire")).json()["item"]["retired"]
    await indexed()
    assert await ids() == {str(keep), str(flagged)}
    assert await ids(show_retired=True) == {str(keep), str(drop), str(flagged)}

    await call(web, "POST", f"/api/bank/items/{drop}/restore")
    await call(web, "POST", f"/api/bank/items/{flagged}/dismiss-flag")
    await indexed()
    assert await ids() == {str(keep), str(drop), str(flagged)}
    assert await ids(flagged=True) == set()


async def test_the_sidebar_counts_the_flagged_items(web):
    before = (await call(web, "GET", "/api/home")).json()["flagged_items"]
    item_id = await items.create_item(closed(), origin="chat", flag_reason="brak wzorca")
    await indexed()

    assert (await call(web, "GET", "/api/home")).json()["flagged_items"] == before + 1

    await call(web, "POST", f"/api/bank/items/{item_id}/dismiss-flag")
    await indexed()

    assert (await call(web, "GET", "/api/home")).json()["flagged_items"] == before


async def test_an_edit_goes_through_the_use_case_and_offers_a_new_solution(web):
    item_id = await items.create_item(open_content(), origin="chat", flag_reason="niepewny skan")

    result = (
        await call(
            web,
            "PATCH",
            f"/api/bank/items/{item_id}",
            json={"text": "Rozwiąż równanie $x^2 = 4$.", "difficulty": "easy"},
        )
    ).json()

    item = result["detail"]["item"]
    assert result["offer_regenerate"] is True
    assert item["flagged"] is False
    # The new text was re-tagged except for what the Teacher set.
    assert item["version"]["difficulty"] == "easy"
    assert [t["id"] for t in item["version"]["curriculum_topics"]] == ["lo2024:V.1"]
    assert item["version"]["number"] == 2


async def test_an_edit_the_item_would_not_hold_changes_nothing(web):
    item_id = await items.create_item(open_content(), origin="chat")

    refused = await call(web, "PATCH", f"/api/bank/items/{item_id}", json={"points": 1})

    assert refused.status_code == 422
    (item,) = await items.get_items([item_id])
    assert item.version.number == 1
