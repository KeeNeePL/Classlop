"""The Classlop AI tab's endpoints over a fake Chat, with no database: the turn relays the Chat's
events as they come, job cards read the Chat's jobs and the near-duplicate buttons reach `items`."""

import asyncio
import uuid

import pytest
from fake_bank import InMemoryBank
from fake_chats import GENERATED, QUESTION, InMemoryChats
from fake_events import InMemoryFeed
from httpx import ASGITransport, AsyncClient

from classlop import items
from classlop.dashboard import auth, chats
from classlop.dashboard.app import create_app


@pytest.fixture
async def tab():
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    fake = InMemoryChats(InMemoryBank(), InMemoryFeed())
    app.dependency_overrides[chats.backend] = lambda: fake
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, fake
    fake.reset()


def frames(body: str) -> list[tuple[str, str]]:
    return [
        tuple(part.split(": ", 1)[1] for part in block.split("\n"))  # type: ignore[misc]
        for block in body.strip().split("\n\n")
    ]


async def test_a_turn_relays_the_chats_events_one_to_one(tab):
    client, fake = tab
    chat = (await client.post("/api/chats")).json()

    sent = await client.post(f"/api/chats/{chat['id']}/messages", data={"text": "zadania"})

    assert sent.headers["content-type"].startswith("text/event-stream")
    assert [
        (name, items.Reply.model_validate_json(data).text) for name, data in frames(sent.text)[:-1]
    ] == [("reply", QUESTION)]
    assert frames(sent.text)[-1] == ("done", "{}")


async def test_a_failing_turn_ends_with_failed_not_done(tab, monkeypatch):
    client, fake = tab
    chat = (await client.post("/api/chats")).json()

    async def broken(*_):
        raise RuntimeError("model down")
        yield

    monkeypatch.setattr(fake, "turn", broken)
    with pytest.raises(RuntimeError):
        await client.post(f"/api/chats/{chat['id']}/messages", data={"text": "zadania"})


async def test_a_job_card_follows_the_generation_and_lists_the_items_it_added(tab):
    client, fake = tab
    chat = (await client.post("/api/chats")).json()
    await client.post(f"/api/chats/{chat['id']}/messages", data={"text": "wygeneruj 3 zadania"})

    (running,) = (await client.get(f"/api/chats/{chat['id']}/jobs")).json()
    badge = (await client.get("/api/chats")).json()[0]
    await asyncio.gather(*fake.tasks)
    (done,) = (await client.get(f"/api/chats/{chat['id']}/jobs")).json()

    assert (running["kind"], running["status"]) == ("generation", "running")
    assert badge["running"] == 1
    assert (done["status"], done["progress"]) == (
        "succeeded",
        {"landed": GENERATED, "total": GENERATED},
    )
    assert len(done["items"]) == GENERATED
    assert (await client.get("/api/chats")).json()[0]["running"] == 0
    reply = (await client.get(f"/api/chats/{chat['id']}/messages")).json()[-1]
    assert reply["payload"]["job_id"] == done["job_id"]


async def test_a_pending_near_duplicate_is_uploaded_anyway_or_dropped_through_items(
    tab, monkeypatch
):
    client, _ = tab
    called = []

    async def anyway(pending_id):
        called.append(("upload", pending_id))

    async def drop(pending_id):
        called.append(("drop", pending_id))

    monkeypatch.setattr(items, "upload_anyway", anyway)
    monkeypatch.setattr(items, "drop_duplicate", drop)
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[chats.backend] = chats.ItemsChats
    first, second = uuid.uuid4(), uuid.uuid4()

    assert (await client.post(f"/api/chats/duplicates/{first}/upload")).status_code == 204
    assert (await client.post(f"/api/chats/duplicates/{second}/drop")).status_code == 204

    assert called == [("upload", first), ("drop", second)]


async def test_a_decision_on_a_near_duplicate_that_is_gone_is_a_404(tab):
    client, _ = tab

    for how in ("upload", "drop"):
        gone = await client.post(f"/api/chats/duplicates/{uuid.uuid4()}/{how}")
        assert gone.status_code == 404
