"""Items against the compose stand-ins (postgres, elasticmq and opensearch), with fake
embeddings and a fake tagger."""

import asyncio
import os
import re
import uuid
import zlib
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import pytest
from opensearchpy import NotFoundError
from sqlalchemy import update

from classlop import items
from classlop.items import CurriculumTopic, ItemContent, RubricLevel, embedding, index
from classlop.items.models import VersionRow
from classlop.shared import jobs, queue, search, worker
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.settings import get_settings

TOPIC = CurriculumTopic(id="lo2024:II.5", name="Równania kwadratowe")


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
    yield
    with suppress(NotFoundError):
        await search.client().indices.delete(index=get_settings().items_index)


def closed(text="Wartość wyrażenia $2^3 - 6$ jest równa:", **kw) -> ItemContent:
    fields: dict[str, Any] = dict(
        item_format="closed",
        text=text,
        points=1,
        difficulty="easy",
        curriculum_topics=[TOPIC],
        general_requirements=["I"],
        options={"A": "$1$", "B": "$2$", "C": "$4$", "D": "$8$"},
        correct_options=["B"],
    )
    return ItemContent(**(fields | kw))


def open_content(text="Rozwiąż równanie $x^2 - 4x - 5 = 0$.", **kw) -> ItemContent:
    fields: dict[str, Any] = dict(
        item_format="open",
        text=text,
        points=2,
        difficulty="medium",
        curriculum_topics=[TOPIC],
        general_requirements=["I", "IV"],
        answer="$x_1 = -1$, $x_2 = 5$",
        model_solution=r"$\Delta = 36$, $x_1 = -1$, $x_2 = 5$",
        rubric=[
            RubricLevel(points=1, description=r"Obliczenie $\Delta = 36$."),
            RubricLevel(points=2, description="Oba pierwiastki."),
        ],
    )
    return ItemContent(**(fields | kw))


async def test_a_created_item_reads_back_with_its_record_and_first_version():
    item_id = await items.create_item(
        open_content(),
        origin="upload",
        source_file="uploads/u1/zestaw.pdf",
        source_page=3,
        exemplar_ids=["ex-1", "ex-2"],
    )

    (item,) = await items.get_items([item_id])
    (version,) = await items.get_versions([item.version.id])

    assert item.id == item_id
    assert (item.origin, item.source_file, item.source_page) == (
        "upload",
        "uploads/u1/zestaw.pdf",
        3,
    )
    assert item.exemplar_ids == ["ex-1", "ex-2"]
    assert (item.flagged, item.retired) == (False, False)
    assert version == item.version
    assert (version.item_id, version.number) == (item_id, 1)
    assert version.text == "Rozwiąż równanie $x^2 - 4x - 5 = 0$."
    assert [(r.points, r.description) for r in version.rubric][0] == (
        1,
        r"Obliczenie $\Delta = 36$.",
    )
    assert version.curriculum_topics == [TOPIC]


class FakeTagger:
    """Tags by the words in the text; counts its calls."""

    def __init__(self):
        self.calls = 0

    async def tag(self, text: str) -> items.Tags:
        self.calls += 1
        return items.Tags(
            difficulty="hard" if "trudne" in text else "easy",
            curriculum_topics=[CurriculumTopic(id="lo2024:V.1", name="Funkcje")],
            general_requirements=["III"],
        )


async def test_an_edit_writes_a_new_version_and_leaves_earlier_ones_unchanged():
    item_id = await items.create_item(closed(), origin="chat", origin_ref="chat-1")
    (before,) = await items.get_items([item_id])

    await items.edit_item(item_id, text="Ile to jest $2^3 - 6$?", tagger=FakeTagger())

    (after,) = await items.get_items([item_id])
    (old,) = await items.get_versions([before.version.id])
    assert (after.version.number, after.version.text) == (2, "Ile to jest $2^3 - 6$?")
    assert after.version.points == before.version.points
    assert old == before.version


async def test_a_stored_version_cannot_be_updated():
    item_id = await items.create_item(closed(), origin="chat")
    (item,) = await items.get_items([item_id])

    with pytest.raises(Exception, match="immutable"):
        async with sessions().begin() as session:
            await session.execute(
                update(VersionRow).where(VersionRow.id == item.version.id).values(points=5)
            )


async def test_a_retag_replaces_the_tags_but_keeps_those_the_teacher_set():
    tagger = FakeTagger()
    item_id = await items.create_item(closed(text="To jest trudne zadanie."), origin="chat")

    await items.edit_item(item_id, difficulty="medium", tagger=tagger)
    await items.retag(item_id, tagger=tagger)
    await items.edit_item(item_id, text="Inne, nadal trudne zadanie.", tagger=tagger)

    (item,) = await items.get_items([item_id])
    v = item.version
    assert v.number == 4
    assert v.difficulty == "medium"  # the Teacher's, though the tagger says hard
    assert v.curriculum_topics == [CurriculumTopic(id="lo2024:V.1", name="Funkcje")]
    assert v.general_requirements == ["III"]


async def test_an_edit_that_leaves_the_text_does_not_retag():
    tagger = FakeTagger()
    item_id = await items.create_item(closed(), origin="chat")

    await items.edit_item(item_id, points=2, tagger=tagger)

    assert tagger.calls == 0


async def test_a_regeneration_is_a_new_version_with_the_tags_it_brings():
    item_id = await items.create_item(closed(), origin="chat")

    await items.new_version(item_id, closed(text="Nowa treść $3 + 4$", difficulty="hard"))

    (item,) = await items.get_items([item_id])
    assert (item.version.number, item.version.difficulty) == (2, "hard")


async def test_retiring_restoring_and_dismissing_a_flag_change_the_item_not_its_versions():
    item_id = await items.create_item(closed(), origin="chat", flag_reason="brak wzorca")
    (item,) = await items.get_items([item_id])
    assert (item.flagged, item.flag_reason) == (True, "brak wzorca")

    await items.dismiss_flag(item_id)
    await items.retire_item(item_id)
    (retired,) = await items.get_items([item_id])
    await items.restore_item(item_id)
    (restored,) = await items.get_items([item_id])

    assert (retired.flagged, retired.retired) == (False, True)
    assert restored.retired is False
    assert restored.version == item.version


async def test_editing_a_flagged_item_dismisses_its_flag():
    item_id = await items.create_item(closed(), origin="chat", flag_reason="sprawdź tekst")

    await items.edit_item(item_id, points=2)

    (item,) = await items.get_items([item_id])
    assert item.flagged is False


async def test_give_pins_the_current_versions_and_an_edit_afterwards_leaves_them():
    a = await items.create_item(closed(text="Pierwsze"), origin="chat")
    b = await items.create_item(open_content(), origin="chat")
    assignment_id, class_id = uuid.uuid4(), uuid.uuid4()
    given_at = datetime(2026, 10, 9, 14, 30, tzinfo=UTC)

    pinned = await items.give([b, a], assignment_id, class_id, given_at)
    await items.edit_item(a, points=3)

    (frozen_b, frozen_a) = await items.get_versions(pinned)
    assert (frozen_b.item_id, frozen_a.item_id) == (b, a)
    assert (frozen_a.number, frozen_a.points) == (1, 1)
    (current,) = await items.get_items([a])
    assert current.version.points == 3
    assert [
        (u.assignment_id, u.class_id, u.given_at, u.version_id) for u in await items.usage(a)
    ] == [(assignment_id, class_id, given_at, pinned[1])]


async def test_give_twice_for_one_assignment_returns_the_same_versions():
    a = await items.create_item(closed(), origin="chat")
    assignment_id, class_id = uuid.uuid4(), uuid.uuid4()
    when = datetime(2026, 10, 9, tzinfo=UTC)

    first = await items.give([a], assignment_id, class_id, when)
    await items.edit_item(a, points=3)
    second = await items.give([a], assignment_id, class_id, when)

    assert first == second
    assert len(await items.usage(a)) == 1


# --- search ---

SYNONYMS = {"auto": "pojazd", "samochód": "pojazd", "samochodu": "pojazd"}


def fake_vector(text: str) -> list[float]:
    """A bag of words hashed into 1536 dimensions, with synonyms sharing a dimension."""
    vector = [0.0] * 1536
    for word in re.findall(r"\w+", text.lower()):
        vector[zlib.crc32((SYNONYMS.get(word) or word).encode()) % 1536] += 1.0
    norm = sum(v * v for v in vector) ** 0.5 or 1.0
    return [v / norm for v in vector]


@pytest.fixture
def fake_embeddings(monkeypatch):
    async def embed(texts: list[str]) -> list[list[float]]:
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(embedding, "embed", embed)


async def indexed() -> None:
    """Run the queued `items.reindex` jobs, as the worker would, and make them searchable."""
    worker.load_handlers()
    while messages := await queue.receive(wait_seconds=1):
        for message in messages:
            await jobs.process(message)
    await search.client().indices.refresh(index=get_settings().items_index)


def marker() -> str:
    """A word no other test's Items contain, so a query finds only this test's Items."""
    return "x" + uuid.uuid4().hex[:10]


async def test_an_inflected_polish_form_of_a_word_finds_the_item(fake_embeddings):
    hit = await items.create_item(
        closed(text="Narysuj wykres: parabola ma wierzchołek."), origin="chat"
    )
    await items.create_item(closed(text="Ile wynosi suma kątów w trójkącie?"), origin="chat")
    await indexed()

    # No token is shared with the text, so only the Polish stemmer links the two forms.
    page = await items.search_items("parabolami", items.Filters())

    assert page.items[0].id == hit


async def test_a_query_finds_an_item_by_meaning_when_no_word_matches(fake_embeddings):
    hit = await items.create_item(
        closed(text="Samochód jedzie ze stałą prędkością."), origin="chat"
    )
    await items.create_item(closed(text="Rozwiąż nierówność liniową."), origin="chat")
    await indexed()

    page = await items.search_items("auto", items.Filters())

    assert page.items[0].id == hit


async def seeded(word: str) -> dict[str, uuid.UUID]:
    """Items sharing `word`, differing in one tag each."""
    ids = {
        "easy_open": await items.create_item(
            open_content(text=f"{word} równanie łatwe", difficulty="easy"), origin="upload"
        ),
        "hard_closed": await items.create_item(
            closed(text=f"{word} równanie trudne", difficulty="hard"), origin="chat"
        ),
        "other_topic": await items.create_item(
            closed(
                text=f"{word} funkcja",
                curriculum_topics=[CurriculumTopic(id="lo2024:V.1", name="Funkcje")],
                general_requirements=["III"],
            ),
            origin="nowa_praca",
            flag_reason="brak wzorca",
        ),
        "retired": await items.create_item(closed(text=f"{word} wycofane"), origin="chat"),
    }
    await items.retire_item(ids["retired"])
    return ids


async def found(word: str, **filters) -> set[uuid.UUID]:
    page = await items.search_items(word, items.Filters(**filters), size=50)
    return {i.id for i in page.items}


async def test_every_filter_narrows_the_results(fake_embeddings):
    word = marker()
    ids = await seeded(word)
    await indexed()

    async def only(**filters) -> set[str]:
        got = await found(word, **filters)
        return {name for name, i in ids.items() if i in got}

    # Text and k-NN both run, so the other tests' Items may come back too; compare ours.
    assert await only() == {"easy_open", "hard_closed", "other_topic"}  # retired left out
    assert await only(retired=True) == {"retired"}
    assert await only(retired=None) == set(ids)
    assert await only(difficulty=["hard"]) == {"hard_closed"}
    assert await only(item_format="open") == {"easy_open"}
    assert await only(curriculum_topics=["lo2024:V.1"]) == {"other_topic"}
    assert await only(curriculum_sections=["lo2024:V"]) == {"other_topic"}
    assert await only(general_requirements=["III"]) == {"other_topic"}
    assert await only(origin=["upload", "nowa_praca"]) == {"easy_open", "other_topic"}
    assert await only(flagged=True) == {"other_topic"}


async def test_never_used_with_a_class_follows_give(fake_embeddings):
    word = marker()
    ids = await seeded(word)
    class_x, class_y = uuid.uuid4(), uuid.uuid4()
    await items.give([ids["easy_open"]], uuid.uuid4(), class_x, datetime.now(UTC))
    await items.give([ids["hard_closed"]], uuid.uuid4(), class_y, datetime.now(UTC))
    await indexed()

    fresh = await found(word, never_used_with_class=class_x)
    used = await found(word, used_with_class=class_x)

    assert ids["easy_open"] not in fresh
    assert {ids["hard_closed"], ids["other_topic"]} <= fresh
    assert ids["easy_open"] in used
    assert not {ids["hard_closed"], ids["other_topic"]} & used


async def test_a_blank_query_lists_the_newest_matching_items_by_page(fake_embeddings):
    word = marker()
    ids = await seeded(word)
    await indexed()
    only_ours = items.Filters(origin=["nowa_praca"], flagged=True, retired=False)

    first = await items.search_items("", only_ours, page=1, size=1)

    assert first.total >= 1
    assert len(first.items) == 1
    assert ids["other_topic"] in {
        i.id for i in (await items.search_items("", only_ours, size=50)).items
    }


async def test_count_items_gives_the_section_by_difficulty_grid(fake_embeddings):
    word = marker()
    class_x = uuid.uuid4()
    a = await items.create_item(
        closed(difficulty="easy", curriculum_topics=[CurriculumTopic(id="lo2024:IX.1", name="a")]),
        origin="chat",
    )
    await items.create_item(
        closed(difficulty="easy", curriculum_topics=[CurriculumTopic(id="lo2024:IX.2", name="b")]),
        origin="chat",
    )
    await items.create_item(
        closed(difficulty="hard", curriculum_topics=[CurriculumTopic(id="lo2024:IX.3", name="c")]),
        origin="chat",
    )
    await items.give([a], uuid.uuid4(), class_x, datetime.now(UTC))
    await indexed()
    assert word

    def grid(counts):
        return {(c.section, c.difficulty): c.count for c in counts if c.section == "lo2024:IX"}

    assert grid(await items.count_items()) == {
        ("lo2024:IX", "easy"): 2,
        ("lo2024:IX", "hard"): 1,
    }
    unused = await items.count_items(items.Filters(never_used_with_class=class_x))
    assert grid(unused) == {("lo2024:IX", "easy"): 1, ("lo2024:IX", "hard"): 1}


async def indexed_document(item_id: uuid.UUID) -> dict:
    index = get_settings().items_index
    if not await search.client().exists(index=index, id=str(item_id)):
        return {}
    return (await search.client().get(index=index, id=str(item_id)))["_source"]


async def test_a_write_reaches_the_index_only_through_the_reindex_job(fake_embeddings):
    item_id = await items.create_item(closed(text="Pierwsza wersja"), origin="chat")
    assert await indexed_document(item_id) == {}

    await indexed()
    assert (await indexed_document(item_id))["text"].startswith("Pierwsza wersja")

    await items.edit_item(item_id, points=4)
    await items.retire_item(item_id)
    await indexed()
    document = await indexed_document(item_id)
    assert (document["points"], document["retired"]) == (4, True)
    assert document["version_id"] == str((await items.get_items([item_id]))[0].version.id)


async def test_reindexing_twice_leaves_one_document(fake_embeddings):
    item_id = await items.create_item(closed(), origin="chat")
    await indexed()
    first = await indexed_document(item_id)

    await index.reindex(item_id)
    await index.reindex(item_id)
    await search.client().indices.refresh(index=get_settings().items_index)

    assert await indexed_document(item_id) == first
    hits = await search.client().count(
        index=get_settings().items_index, body={"query": {"term": {"item_id": str(item_id)}}}
    )
    assert hits["count"] == 1


async def test_rebuild_index_refills_a_lost_index_from_postgres(fake_embeddings, monkeypatch):
    monkeypatch.setattr(get_settings(), "items_index", f"{get_settings().items_index}-rebuild")
    word = marker()
    item_id = await items.create_item(closed(text=f"Odbudowa {word}"), origin="chat")
    # The job for this write never runs: the index has to come from Postgres alone.

    count = await index.rebuild()

    assert count >= 1
    try:
        page = await items.search_items(word, items.Filters())
        assert page.items[0].id == item_id
    finally:
        await search.client().indices.delete(index=get_settings().items_index)


async def test_a_regeneration_keeps_the_tags_the_teacher_set_marked(fake_embeddings):
    tagger = FakeTagger()
    item_id = await items.create_item(closed(), origin="chat")
    await items.edit_item(item_id, difficulty="medium", tagger=tagger)

    await items.new_version(item_id, closed(text="Nowa treść $5 + 5$", difficulty="medium"))
    await items.retag(item_id, tagger=tagger)

    (item,) = await items.get_items([item_id])
    assert (item.version.number, item.version.difficulty) == (4, "medium")


async def test_unknown_ids_and_unknown_edits_are_refused():
    unknown = uuid.uuid4()
    item_id = await items.create_item(closed(), origin="chat")

    for call in (
        items.get_items([unknown]),
        items.get_versions([unknown]),
        items.give([item_id, unknown], uuid.uuid4(), uuid.uuid4(), datetime.now(UTC)),
        items.retire_item(unknown),
    ):
        with pytest.raises(LookupError):
            await call
    with pytest.raises(TypeError):
        await items.edit_item(item_id, pointz=3)  # type: ignore[call-arg]
    assert await items.give([], uuid.uuid4(), uuid.uuid4(), datetime.now(UTC)) == []
    assert await items.usage(item_id) == []


async def test_an_edit_that_loses_a_race_is_refused_not_merged():
    item_id = await items.create_item(closed(text="Trudne zadanie"), origin="chat")

    class Racing(FakeTagger):
        async def tag(self, text: str) -> items.Tags:
            await items.edit_item(item_id, points=7)  # lands while this edit is tagging
            return await super().tag(text)

    with pytest.raises(RuntimeError, match="changed"):
        await items.edit_item(item_id, text="Inny tekst", tagger=Racing())

    (item,) = await items.get_items([item_id])
    assert (item.version.number, item.version.text) == (2, "Trudne zadanie")


async def test_a_reindex_that_read_postgres_earlier_does_not_overwrite_a_later_one(
    fake_embeddings, monkeypatch
):
    item_id = await items.create_item(closed(), origin="chat")
    await indexed()
    await items.edit_item(item_id, points=4)

    real_clock = index._clock
    monkeypatch.setattr(index, "_clock", lambda: 1)  # a job whose read came first
    await index.reindex(item_id)
    assert (await indexed_document(item_id))["points"] == 1

    monkeypatch.setattr(index, "_clock", real_clock)
    await index.reindex(item_id)
    assert (await indexed_document(item_id))["points"] == 4
