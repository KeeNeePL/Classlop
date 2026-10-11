"""The Classlop AI Chat graph against the compose stand-ins (postgres, elasticmq, opensearch and
s3), with a scripted model, a fake tagger and fake embeddings. Generation and upload are recorded,
not run: their own tests cover them."""

import asyncio
import os
import uuid
from contextlib import suppress

import pytest
from opensearchpy import NotFoundError
from test_generation import FakeTagger, tags
from test_items import fake_vector, open_content

from classlop import items
from classlop.items import chat_graph, embedding, index
from classlop.items.chat_graph import Turn
from classlop.items.generation import Draft
from classlop.items.upload import Started
from classlop.shared import llm, queue, search, storage
from classlop.shared.migrate import migrate
from classlop.shared.settings import get_settings

DRAFT_FIELDS = {"item_format", "text", "points", "answer", "model_solution", "rubric"}
EASY_CLOSED = items.Line(count=5, difficulty="easy", item_format="closed")


@pytest.fixture(scope="module", autouse=True)
async def stack():
    try:
        await asyncio.to_thread(migrate)
        await asyncio.to_thread(queue.url)
        await asyncio.to_thread(storage.ping)
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
    await chat_graph.close()


class ScriptedModel:
    """Answers each Chat turn with the next queued Turn and each revision with the next Draft;
    keeps what it was asked."""

    def __init__(self, monkeypatch):
        self.turns: list[Turn] = []
        self.drafts: list[Draft] = []
        self.asked: list[list] = []
        self.revisions: list[list] = []
        monkeypatch.setattr(llm, "ask", self.ask)

    async def ask(self, job, schema, messages):
        if schema is Draft:
            self.revisions.append(messages)
            return self.drafts.pop(0)
        self.asked.append(messages)
        return self.turns.pop(0)


class Recorder:
    def __init__(self, monkeypatch):
        self.generations: list[tuple[items.GenerationSpec, items.GenerationOrigin]] = []
        self.uploads: list[tuple[str, str, bytes]] = []
        monkeypatch.setattr(chat_graph, "request_generation", self.generate)
        monkeypatch.setattr(chat_graph, "request_upload", self.upload)

    async def generate(self, spec, origin):
        self.generations.append((spec, origin))
        return uuid.uuid4()

    async def upload(self, chat_id, filename, data):
        self.uploads.append((chat_id, filename, data))
        return Started(upload_id=uuid.uuid4(), job_id=uuid.uuid4())


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    async def embed(texts: list[str]) -> list[list[float]]:
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(embedding, "embed", embed)


@pytest.fixture
def model(monkeypatch):
    return ScriptedModel(monkeypatch)


@pytest.fixture
def recorded(monkeypatch):
    return Recorder(monkeypatch)


@pytest.fixture
def fake_tagger(monkeypatch):
    return FakeTagger(monkeypatch)


def ask(reply: str) -> Turn:
    return Turn(action="ask", reply=reply)


def generate(reply: str, *lines: items.Line) -> Turn:
    return Turn(action="generate", reply=reply, spec=items.GenerationSpec(lines=list(lines)))


async def say(chat_id: str, text: str, file: tuple[str, bytes] | None = None) -> list:
    return [event async for event in chat_graph.take_turn(chat_id, text, file)]


async def chat_with_items(n: int = 5) -> tuple[str, list[uuid.UUID]]:
    chat = await items.create_chat()
    ids = [
        await items.create_item(
            open_content(f"Zadanie numer {i}"), origin="chat", origin_ref=chat.id
        )
        for i in range(1, n + 1)
    ]
    return chat.id, ids


async def text_of(item_id: uuid.UUID) -> str:
    (item,) = await items.get_items([item_id])
    return item.version.text


async def test_the_ai_asks_until_the_request_is_clear_then_generates_without_confirming(
    model, recorded
):
    chat = await items.create_chat()
    model.turns = [
        ask("Ile zadań, jakiej trudności i w jakim formacie?"),
        ask("Z jakiego tematu?"),
        generate("Zaczynam generować 5 łatwych zadań zamkniętych.", EASY_CLOSED),
    ]

    first = await say(chat.id, "Potrzebuję zadań z nierówności")
    assert recorded.generations == []
    second = await say(chat.id, "5 łatwych")
    assert recorded.generations == []
    third = await say(chat.id, "zamkniętych")

    (spec, origin) = recorded.generations[0]
    assert spec.lines == [EASY_CLOSED]
    assert origin == items.GenerationOrigin(kind="chat", chat_id=chat.id)
    assert first[-1].text.startswith("Ile zadań")
    assert second[-1].text == "Z jakiego tematu?"
    assert third[-1].payload["job_id"]
    assert [(m.role, m.text) for m in await items.chat_messages(chat.id)][-2:] == [
        ("user", "zamkniętych"),
        ("assistant", "Zaczynam generować 5 łatwych zadań zamkniętych."),
    ]


async def test_the_model_sees_the_whole_conversation_of_the_chat(model, recorded):
    chat = await items.create_chat()
    model.turns = [ask("Ile?"), ask("Jaka trudność?")]

    await say(chat.id, "Zadania z ciągów")
    await say(chat.id, "pięć")

    sent = [m.content for m in model.asked[-1] if m.type != "system"]
    assert sent == ["Zadania z ciągów", "Ile?", "pięć"]


async def test_the_conversation_survives_a_restart_of_the_graph(model, recorded):
    chat = await items.create_chat()
    model.turns = [ask("Ile?"), ask("Jaka trudność?")]
    await say(chat.id, "Zadania z ciągów")

    await chat_graph.close()
    await say(chat.id, "pięć")

    assert "Zadania z ciągów" in [m.content for m in model.asked[-1]]


async def test_an_attached_file_always_starts_an_item_upload(model, recorded):
    chat = await items.create_chat()

    events = await say(chat.id, "", ("zestaw.pdf", b"%PDF"))

    assert recorded.uploads == [(chat.id, "zestaw.pdf", b"%PDF")]
    assert model.asked == []
    assert events[-1].payload["upload_id"] and events[-1].payload["job_id"]


async def test_a_file_with_a_message_still_starts_an_upload_not_a_generation(model, recorded):
    chat = await items.create_chat()
    model.turns = [generate("Generuję.", EASY_CLOSED)]

    await say(chat.id, "zrób takie same", ("zestaw.png", b"png"))

    assert len(recorded.uploads) == 1
    assert recorded.generations == []


async def test_a_follow_up_writes_a_new_version_of_the_item_it_names(model, recorded, fake_tagger):
    chat_id, ids = await chat_with_items()
    fake_tagger.default = tags("easy")
    model.drafts = [Draft(**open_content("Łatwiejsze zadanie").model_dump(include=DRAFT_FIELDS))]
    model.turns = [
        Turn(action="revise", reply="Ułatwiam zadanie 3.", number=3, instruction="łatwiejsze")
    ]

    events = await say(chat_id, "zrób trzecie łatwiejsze")

    assert await text_of(ids[2]) == "Łatwiejsze zadanie"
    assert [await text_of(i) for i in ids if i != ids[2]] == [
        f"Zadanie numer {n}" for n in (1, 2, 4, 5)
    ]
    (item,) = await items.get_items([ids[2]])
    assert item.version.number == 2 and item.version.difficulty == "easy"
    assert events[-1].payload == {"item_id": str(ids[2]), "version": 2}
    brief = model.revisions[0][1].content
    assert "Zadanie numer 3" in brief and "łatwiejsze" in brief


async def test_a_follow_up_retires_the_item_it_names_and_numbers_stay_put(model, recorded):
    chat_id, ids = await chat_with_items()
    model.turns = [
        Turn(action="retire", reply="Wyrzucam zadanie 5.", number=5),
        Turn(action="retire", reply="Wyrzucam zadanie 4.", number=4),
    ]

    await say(chat_id, "wyrzuć piąte")
    await say(chat_id, "i czwarte")

    retired = [i.retired for i in await items.get_items(ids)]
    assert retired == [False, False, False, True, True]


async def test_the_model_is_told_the_numbered_items_of_the_chat(model, recorded):
    chat_id, ids = await chat_with_items(3)
    await items.retire_item(ids[1])
    model.turns = [ask("Co zmienić?")]

    await say(chat_id, "popraw jedno")

    system = model.asked[0][0].content
    assert "3. Zadanie numer 3" in system
    assert "2. (wyrzucone) Zadanie numer 2" in system


async def test_more_of_the_same_is_a_new_generation_request_in_the_same_chat(model, recorded):
    chat_id, _ = await chat_with_items()
    more = items.Line(count=3, difficulty="easy", item_format="closed")
    model.turns = [generate("Dorzucam 3 zadania.", more)]

    await say(chat_id, "dorzuć 3")

    ((spec, origin),) = recorded.generations
    assert spec.lines == [more] and origin.chat_id == chat_id


async def test_a_number_the_chat_has_no_item_for_gets_an_answer_not_a_change(model, recorded):
    chat_id, ids = await chat_with_items(2)
    model.turns = [Turn(action="retire", reply="Wyrzucam.", number=7)]

    events = await say(chat_id, "wyrzuć siódme")

    assert [i.retired for i in await items.get_items(ids)] == [False, False]
    assert "7" in events[-1].text and "2" in events[-1].text


def test_an_action_without_what_it_needs_is_rejected():
    with pytest.raises(ValueError):
        Turn(action="generate", reply="x")
    with pytest.raises(ValueError):
        Turn(action="revise", reply="x", number=1)
    with pytest.raises(ValueError):
        Turn(action="retire", reply="x")


async def test_items_of_other_chats_do_not_count(model, recorded):
    mine, ids = await chat_with_items(2)
    await chat_with_items(3)
    model.turns = [Turn(action="retire", reply="Wyrzucam.", number=3)]

    await say(mine, "wyrzuć trzecie")

    assert [i.retired for i in await items.get_items(ids)] == [False, False]


async def test_chats_are_named_renamable_and_deletable_and_deleting_keeps_the_items(
    model, recorded
):
    chat_id, ids = await chat_with_items(2)
    model.turns = [ask("Co dalej?")]
    await say(chat_id, "Cześć")
    await items.rename_chat(chat_id, "Ciągi, klasa 2b")

    assert (await items.get_chat(chat_id)).name == "Ciągi, klasa 2b"
    assert chat_id in [c.id for c in await items.chats()]

    await items.delete_chat(chat_id)

    assert chat_id not in [c.id for c in await items.chats()]
    assert await items.chat_messages(chat_id) == []
    assert len(await items.get_items(ids)) == 2
    with pytest.raises(LookupError):
        await say(chat_id, "jeszcze jedno")


async def test_a_new_chat_is_named_after_its_first_message(model, recorded):
    chat = await items.create_chat()
    model.turns = [ask("Ile?")]

    await say(chat.id, "Potrzebuję zadań z ciągów arytmetycznych dla klasy drugiej")

    assert (await items.get_chat(chat.id)).name.startswith("Potrzebuję zadań z ciągów")


@pytest.fixture
async def web():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from classlop.dashboard import auth, chats

    app = FastAPI()
    app.include_router(chats.router)
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_a_message_over_http_streams_the_replies_as_server_sent_events(web, model, recorded):
    chat = (await web.post("/api/chats", json={"name": "Nierówności"})).json()
    model.turns = [ask("Ile zadań?")]

    sent = await web.post(f"/api/chats/{chat['id']}/messages", data={"text": "zadania"})

    assert sent.headers["content-type"].startswith("text/event-stream")
    assert sent.text.startswith('event: reply\ndata: {"text":"Ile zadań?"')
    assert sent.text.endswith("event: done\ndata: {}\n\n")
    stored = (await web.get(f"/api/chats/{chat['id']}/messages")).json()
    assert [m["role"] for m in stored] == ["user", "assistant"]


async def test_a_file_over_http_starts_an_upload(web, model, recorded):
    chat = (await web.post("/api/chats")).json()

    sent = await web.post(
        f"/api/chats/{chat['id']}/messages", files={"file": ("zestaw.pdf", b"%PDF")}
    )

    assert recorded.uploads == [(chat["id"], "zestaw.pdf", b"%PDF")]
    assert "event: done" in sent.text


async def test_chats_over_http_rename_delete_and_refuse_the_unknown(web, model, recorded):
    chat = (await web.post("/api/chats")).json()

    assert (await web.patch(f"/api/chats/{chat['id']}", json={"name": "Ciągi"})).status_code == 200
    assert (await web.patch(f"/api/chats/{chat['id']}", json={"name": " "})).status_code == 422
    assert "Ciągi" in [c["name"] for c in (await web.get("/api/chats")).json()]
    assert (await web.delete(f"/api/chats/{chat['id']}")).status_code == 204
    assert (await web.get(f"/api/chats/{chat['id']}/messages")).status_code == 404
    assert (await web.post("/api/chats/nope/messages", data={"text": "x"})).status_code == 404
    assert (await web.post(f"/api/chats/{chat['id']}/messages", data={})).status_code == 404
