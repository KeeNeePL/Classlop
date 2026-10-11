"""Item uploads against the compose stand-ins (postgres, elasticmq, opensearch and s3), with a
fake vision/completion model, a fake tagger and fake embeddings. The files are invented."""

import asyncio
import io
import json
import os
import uuid
from contextlib import suppress

import pytest
from opensearchpy import NotFoundError
from PIL import Image, ImageDraw
from test_generation import FakeTagger, tags
from test_items import fake_vector, open_content

from classlop import items
from classlop.items import embedding, index
from classlop.items.generation import Draft
from classlop.items.upload import Exercise, PageReading
from classlop.shared import jobs, llm, queue, search, storage, worker
from classlop.shared.migrate import migrate
from classlop.shared.settings import get_settings

CHAT = "chat-upload"


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


def exercise(label, text, confidence=0.95, **kw) -> Exercise:
    return Exercise(label=label, text=text, confidence=confidence, box=[0.1, 0.1, 0.9, 0.4], **kw)


class FakeVision:
    """Reads the queued PageReading for each page asked; completes every exercise as an Item of
    its own text, closed when the text starts with "CLOSED"."""

    def __init__(self, monkeypatch):
        self.readings: list[PageReading] = []
        self.broken = False
        monkeypatch.setattr(llm, "ask", self.ask)

    async def ask(self, job, schema, messages):
        if schema is PageReading:
            return self.readings.pop(0)
        given = json.loads(messages[1].content)
        if self.broken:
            return Draft(item_format="open", text=given["text"], points=1)
        if given["text"].startswith("CLOSED"):
            return Draft(
                item_format="closed",
                text=given["text"],
                points=1,
                options={"A": "$1$", "B": "$2$"},
                correct_options=["B"],
            )
        return Draft(
            item_format="open",
            text=given["text"],
            points=1,
            answer="$0$",
            model_solution="$0$",
            rubric=[items.RubricLevel(points=1, description="Wynik.")],
        )


@pytest.fixture
def vision(monkeypatch):
    return FakeVision(monkeypatch)


@pytest.fixture
def fake_tagger(monkeypatch):
    return FakeTagger(monkeypatch)


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    async def embed(texts: list[str]) -> list[list[float]]:
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(embedding, "embed", embed)
    worker.load_handlers()


def typed_pdf() -> bytes:
    from classlop.shared.typeset import Heading, Paragraph, render

    return render([Heading("Zestaw A"), Paragraph("Zadanie 1. Oblicz pole kwadratu o boku 3.")])


def photo() -> bytes:
    page = Image.new("RGB", (800, 1100), "white")
    ImageDraw.Draw(page).text((60, 100), "Zadanie 2. Rozwiaz rownanie", fill="black")
    out = io.BytesIO()
    page.save(out, "JPEG")
    return out.getvalue()


async def run(data: bytes, filename: str) -> dict:
    started = await items.request_upload(CHAT, filename, data)
    while messages := await queue.receive(wait_seconds=1):
        for message in messages:
            await jobs.process(message)
    (job,) = await jobs.get_jobs([started.job_id])
    assert job.status == "succeeded", job.error
    assert job.result["upload_id"] == str(started.upload_id)
    return job.result


async def seed(content) -> uuid.UUID:
    item_id = await items.create_item(content, origin="chat", origin_ref="earlier")
    await index.reindex(item_id)
    await search.client().indices.refresh(index=get_settings().items_index)
    return item_id


async def test_an_invented_pdf_and_photo_become_items_skips_a_flag_and_a_pending_duplicate(
    vision, fake_tagger
):
    taken = open_content(
        text="Pole kwadratu bok trzy oblicz powierzchnie figury",
        curriculum_topics=tags().curriculum_topics,
    )
    taken_id = await seed(taken)
    vision.readings = [
        PageReading(
            exercises=[
                exercise(
                    "1",
                    "Wyznacz miare kata miedzy przekatnymi prostokata",
                    answer="$90$",
                    points=1,
                ),
                exercise("2", "Na rysunku widac trojkat zaznacz wysokosc", skip="figure_dependent"),
                exercise("3", taken.text),
            ]
        ),
        PageReading(
            exercises=[
                exercise("1", "CLOSED Ktora liczba jest pierwsza spomiedzy podanych"),
                exercise("2", "Ile wynosi suma pierwiastkow rownania", confidence=0.4),
                exercise("3", "Oblicz calke oznaczona z funkcji", skip="no_basic_topic"),
            ]
        ),
    ]

    first = await run(typed_pdf(), "zestaw a.pdf")
    second = await run(photo(), "zdjecie.jpg")

    assert [e["label"] for e in first["items"]] == ["1"]
    assert [(e["label"], e["reason"]) for e in first["skipped"]] == [("2", "zależne od rysunku")]
    assert [e["label"] for e in first["pending"]] == ["3"]
    assert first["pending"][0]["nearest_item_id"] == str(taken_id)
    assert [(e["label"], e["flagged"]) for e in second["items"]] == [("1", False), ("2", True)]
    assert [e["reason"] for e in second["skipped"]] == ["brak tematu z poziomu podstawowego"]

    (made,) = await items.get_items([uuid.UUID(first["items"][0]["item_id"])])
    assert made.origin == "upload" and made.origin_ref == CHAT
    assert made.source_page == 1 and made.source_file.endswith("/zestaw a.pdf")
    # The Teacher's own answer and points are kept, the rest comes from the AI.
    assert made.version.answer == "$90$" and made.version.points == 1
    assert made.version.curriculum_topics == tags().curriculum_topics

    flagged_entry = second["items"][1]
    (flagged,) = await items.get_items([uuid.UUID(flagged_entry["item_id"])])
    assert flagged.flagged and flagged.flag_reason == "sprawdź tekst zadania"
    links = await items.upload_links(uuid.UUID(second["upload_id"]))
    assert links.file and set(links.crops) == {"p1-1.jpg", "p1-2.jpg", "p1-3.jpg"}
    assert flagged_entry["crop"] in links.crops
    key = f"items/uploads/{second['upload_id']}/crops/{flagged_entry['crop']}"
    crop = Image.open(io.BytesIO(storage.get(key)))
    assert crop.width < 800 and crop.height < 1100
    assert set(links.pages) == {"1.jpg"}

    messages = await items.chat_messages(CHAT)
    assert [m.payload["summary"]["upload_id"] for m in messages] == [
        first["upload_id"],
        second["upload_id"],
    ]
    assert "zadań w banku 2 (do sprawdzenia 1)" in messages[1].text

    (pending,) = await items.pending_duplicates(uuid.UUID(first["upload_id"]))
    assert pending.content.text == taken.text and pending.nearest_item_id == taken_id
    # A pending near-duplicate is not an Item: the bank holds the seeded Item once.
    found = await items.search_items(taken.text, items.Filters(origin=["chat"]), page=1)
    assert [i.id for i in found.items] == [taken_id]


async def test_upload_anyway_makes_an_item_drop_deletes_and_undecided_stay_pending(
    vision, fake_tagger
):
    first_text = "Rozwiaz uklad rownan z dwiema niewiadomymi metoda przeciwnych wspolczynnikow"
    second_text = "Wyznacz dziedzine funkcji wymiernej o mianowniku kwadratowym"
    undecided_text = "Oblicz wartosc wyrazenia potegowego z wykladnikiem ujemnym"
    for text in (first_text, second_text, undecided_text):
        await seed(open_content(text=text, curriculum_topics=tags().curriculum_topics))
    vision.readings = [
        PageReading(
            exercises=[
                exercise("1", first_text, confidence=0.3),
                exercise("2", second_text),
                exercise("3", undecided_text),
            ]
        )
    ]
    summary = await run(photo(), "powtorki.jpg")
    upload_id = uuid.UUID(summary["upload_id"])
    one, two, three = await items.pending_duplicates(upload_id)

    made_id = await items.upload_anyway(one.id)
    await items.drop_duplicate(two.id)

    (made,) = await items.get_items([made_id])
    assert made.origin == "upload" and made.source_page == 1
    # The Extraction was unsure, so the Item is Flagged.
    assert made.flagged and made.flag_reason == "sprawdź tekst zadania"
    assert [p.id for p in await items.pending_duplicates(upload_id)] == [three.id]
    with pytest.raises(LookupError):
        await items.upload_anyway(one.id)
    with pytest.raises(LookupError):
        await items.drop_duplicate(two.id)


async def test_a_file_that_is_no_image_or_pdf_says_so_in_the_chat(vision, fake_tagger):
    summary = await run(b"not a page", "dziwny.bin")

    assert summary["pages"] == 0 and summary["items"] == []
    last = (await items.chat_messages(CHAT))[-1]
    assert last.text == "Nie udało się odczytać pliku dziwny.bin."


async def test_an_exercise_the_ai_cannot_complete_is_skipped_with_its_reason(vision, fake_tagger):
    vision.broken = True
    vision.readings = [PageReading(exercises=[exercise("1", "Dziwne zadanie bez rozwiazania")])]

    summary = await run(photo(), "zepsute.jpg")

    assert summary["items"] == []
    assert [e["reason"] for e in summary["skipped"]] == ["nie udało się dopisać rozwiązania"]
