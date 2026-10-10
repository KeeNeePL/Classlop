"""The `items` records and the Item bank search, against Postgres, OpenSearch and the job queue
from compose, with a fake tagger and fake embeddings."""

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from classlop import items
from classlop.items import (
    CurriculumTopic,
    Difficulty,
    Item,
    ItemContent,
    ItemFilters,
    RubricLevel,
    Tags,
    Usage,
    index,
    records,
    tagging,
)
from classlop.items.index import DIMENSIONS
from classlop.items.records import add_item, revise_item
from classlop.shared import jobs, llm, queue, search, worker
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.models import Job
from classlop.shared.settings import get_settings

QUADRATIC = CurriculumTopic(id="lo2024:IV.1", name="Równania kwadratowe")
POWERS = CurriculumTopic(id="lo2024:I.3", name="Potęgi o wykładnikach wymiernych")


@pytest.fixture(scope="module", autouse=True)
async def stack():
    try:
        await asyncio.to_thread(migrate)
        await asyncio.to_thread(queue.url)
        await search.ping()
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip(
            "compose stand-ins are not running: docker compose up -d postgres opensearch elasticmq"
        )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(llm, "embeddings", ConceptEmbeddings)
        task = asyncio.create_task(run_worker())
        yield
        task.cancel()
    await search.client().indices.delete(index=f"{get_settings().items_index}-*")


async def run_worker():
    worker.load_handlers()
    while True:
        for message in await queue.receive(wait_seconds=1):
            await jobs.process(message)


class ConceptEmbeddings:
    """Texts that share a concept point the same way, whatever words they use."""

    CONCEPTS = {"pole": 1, "powierzchni": 1, "równani": 2, "koł": 3}

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        vector[0] = 1.0
        for word in text.lower().split():
            for stem, dimension in self.CONCEPTS.items():
                if word.startswith(stem):
                    vector[dimension] = 1.0
        return vector

    async def aembed_query(self, text: str) -> list[float]:
        return self._embed(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]


async def settled(*written: Item) -> None:
    """Waits until every reindex job of these Items has run and its write is searchable."""
    ids = [str(i.id) for i in written]

    async def pending():
        async with sessions()() as session:
            statuses = await session.scalars(
                select(Job.status).where(
                    Job.kind == "items.reindex", Job.payload["item_id"].astext.in_(ids)
                )
            )
            statuses = list(statuses)
        assert "failed" not in statuses
        return [s for s in statuses if s != "succeeded"]

    async with asyncio.timeout(20):
        while await pending():
            await asyncio.sleep(0.2)
    await search.client().indices.refresh(index=get_settings().items_index)


def open_item(text="Rozwiąż równanie $x^2 - 4x - 5 = 0$.") -> ItemContent:
    return ItemContent(
        item_format="open",
        text=text,
        points=2,
        answer="$x = -1$ lub $x = 5$",
        model_solution=r"$\Delta = 36$, $x_1 = -1$, $x_2 = 5$",
        rubric=[
            RubricLevel(points=1, description=r"Obliczenie $\Delta = 36$."),
            RubricLevel(points=2, description="Oba pierwiastki."),
        ],
    )


def closed_item(text=r"Wartość wyrażenia $8^{\frac{2}{3}}$ jest równa:") -> ItemContent:
    return ItemContent(
        item_format="closed",
        text=text,
        points=1,
        options={"A": "$2$", "B": "$4$", "C": "$6$", "D": "$16$"},
        correct_options=["B"],
    )


def own_topic() -> CurriculumTopic:
    """In a section of its own, so a test sees only its own Items in a shared database."""
    return CurriculumTopic(id=f"lo2024:T{uuid.uuid4().hex[:8]}.1", name="Temat testowy")


def tags(difficulty: Difficulty = "medium", topics=(QUADRATIC,), requirements=("II",)) -> Tags:
    return Tags(
        difficulty=difficulty,
        curriculum_topics=list(topics),
        general_requirements=list(requirements),
        probabilities={f"difficulty:{difficulty}": 0.9},
    )


async def test_an_added_item_reads_back_as_written():
    item = await add_item(
        closed_item(),
        tags(topics=[POWERS], requirements=["I"]),
        origin="uploaded",
        source_key="items/uploads/u1/kartkowka.pdf",
        source_page=2,
        exemplar_ids=["zpe:123"],
        flag="unsure_extraction",
    )

    (read,) = await items.get_items([item.id])
    assert read == item
    assert read.origin == "uploaded"
    assert (read.source_key, read.source_page) == ("items/uploads/u1/kartkowka.pdf", 2)
    assert read.exemplar_ids == ["zpe:123"]
    assert read.flag == "unsure_extraction"
    assert not read.retired
    (version,) = await items.get_versions([read.version.id])
    assert version.item_id == item.id
    assert version.options == {"A": "$2$", "B": "$4$", "C": "$6$", "D": "$16$"}
    assert version.correct_options == ["B"]
    assert version.curriculum_topics == [POWERS]
    assert (version.difficulty, version.general_requirements) == ("medium", ["I"])


@pytest.fixture
def tagger(monkeypatch):
    """The fake tagging interface: whatever tags were last set, and the texts it was sent."""

    class Tagger:
        def __init__(self):
            self.tags = tags()
            self.sent: list[str] = []

        async def tag(self, content: ItemContent) -> Tags:
            self.sent.append(content.text)
            return self.tags

    fake = Tagger()
    monkeypatch.setattr(tagging, "tag", fake.tag)
    return fake


async def test_an_edit_writes_a_new_version_and_leaves_the_old_one(tagger):
    item = await add_item(open_item(), tags(), origin="generated", flag="failed_tag_check")
    tagger.tags = tags("hard", topics=[QUADRATIC, POWERS], requirements=["III"])

    edited = await items.edit_item(
        item.id, open_item("Rozwiąż równanie $x^2 - 9 = 0$."), difficulty="easy"
    )

    assert edited.version.id != item.version.id
    assert edited.version.text == "Rozwiąż równanie $x^2 - 9 = 0$."
    assert tagger.sent == ["Rozwiąż równanie $x^2 - 9 = 0$."]
    assert edited.version.difficulty == "easy"
    assert edited.version.curriculum_topics == [QUADRATIC, POWERS]
    assert edited.version.general_requirements == ["III"]
    assert edited.flag is None
    assert await items.get_versions([item.version.id]) == [item.version]


async def test_tags_the_teacher_set_survive_a_retag_and_a_regeneration(tagger):
    item = await add_item(open_item(), tags(), origin="generated")
    await items.edit_item(item.id, open_item(), curriculum_topics=[POWERS])
    tagger.tags = tags("hard", topics=[QUADRATIC], requirements=["IV"])

    retagged = await items.retag_item(item.id)
    regenerated = await revise_item(
        item.id, open_item("Rozwiąż równanie $x^2 = 4$."), tags("easy", requirements=["I"])
    )

    assert retagged.version.curriculum_topics == [POWERS]
    assert (retagged.version.difficulty, retagged.version.general_requirements) == ("hard", ["IV"])
    assert regenerated.version.curriculum_topics == [POWERS]
    assert (regenerated.version.difficulty, regenerated.version.text) == (
        "easy",
        "Rozwiąż równanie $x^2 = 4$.",
    )
    (current,) = await items.get_items([item.id])
    assert current.version == regenerated.version
    assert len({item.version.id, retagged.version.id, regenerated.version.id}) == 3


async def test_give_pins_versions_that_a_later_edit_leaves_alone(tagger):
    first = await add_item(open_item(), tags(), origin="generated")
    second = await add_item(closed_item(), tags(), origin="generated")
    assignment_id, given_at = uuid.uuid4(), datetime(2026, 10, 12, 8, 0, tzinfo=UTC)

    pinned = await items.give([second.id, first.id], assignment_id, "class-2b", given_at)
    await items.edit_item(first.id, open_item("Rozwiąż równanie $x^2 = 1$."))

    assert pinned == [second.version.id, first.version.id]
    assert await items.get_versions(pinned) == [second.version, first.version]
    assert await items.usage(first.id) == [
        Usage(
            assignment_id=assignment_id,
            class_id="class-2b",
            version_id=first.version.id,
            given_at=given_at,
        )
    ]
    # A retried give keeps what was pinned the first time.
    assert await items.give([second.id, first.id], assignment_id, "class-2b", given_at) == pinned


async def test_the_teacher_retires_restores_and_dismisses_a_flag():
    item = await add_item(open_item(), tags(), origin="generated", flag="no_exemplar")

    retired = await items.retire_item(item.id)
    restored = await items.restore_item(item.id)
    dismissed = await items.dismiss_flag(item.id)

    assert retired.retired and not restored.retired
    assert (restored.flag, dismissed.flag) == ("no_exemplar", None)
    assert dismissed.version == item.version


async def test_search_finds_an_item_by_an_inflected_word():
    item = await add_item(
        closed_item("Obwód trójkąta równobocznego wynosi $12$. Bok ma długość:"),
        tags(),
        origin="generated",
    )
    await settled(item)

    page = await items.search_items("trójkątów")

    assert page.items[0] == item


async def test_search_finds_an_item_by_meaning():
    item = await add_item(
        open_item("Oblicz pole koła o promieniu $2$."), tags(), origin="generated"
    )
    await settled(item)

    page = await items.search_items("powierzchnia")

    assert page.items[0] == item


async def test_every_filter_narrows_the_bank():
    topic = own_topic()
    a = await add_item(
        closed_item(), tags("easy", [topic], ["I"]), origin="uploaded", source_page=1
    )
    b = await add_item(
        open_item(), tags("hard", [topic], ["III"]), origin="generated", flag="no_exemplar"
    )
    c = await add_item(open_item(), tags("medium", [topic], ["II"]), origin="generated")
    await items.retire_item(c.id)
    await settled(a, b, c)

    async def found(query="", **filters) -> set:
        own = ItemFilters(curriculum_topics=[topic.id], **filters)
        return {i.id for i in (await items.search_items(query, own)).items}

    assert await found() == {a.id, b.id}
    assert await found(difficulty=["hard"]) == {b.id}
    assert await found(general_requirements=["I", "IV"]) == {a.id}
    assert await found(item_format="closed") == {a.id}
    assert await found(flagged=True) == {b.id}
    assert await found(flagged=False) == {a.id}
    assert await found(origin="uploaded") == {a.id}
    assert await found(retired=True) == {c.id}
    assert await found("równanie", difficulty=["hard"]) == {b.id}
    sections = ItemFilters(curriculum_sections=[topic.section])
    assert {i.id for i in (await items.search_items("", sections)).items} == {a.id, b.id}


async def test_never_used_with_a_class_leaves_out_what_it_was_given():
    topic = own_topic()
    given = await add_item(open_item(), tags(topics=[topic]), origin="generated")
    fresh = await add_item(open_item(), tags(topics=[topic]), origin="generated")
    await items.give([given.id], uuid.uuid4(), "class-1a", datetime.now(UTC))
    await settled(given, fresh)

    async def found(class_id) -> set:
        filters = ItemFilters(curriculum_topics=[topic.id], never_used_with_class=class_id)
        return {i.id for i in (await items.search_items("", filters)).items}

    assert await found("class-1a") == {fresh.id}
    assert await found("class-3c") == {given.id, fresh.id}


async def test_count_items_per_section_and_difficulty():
    one, two = own_topic(), own_topic()
    bank: list[tuple[Difficulty, list[CurriculumTopic]]] = [
        ("easy", [one]),
        ("easy", [one]),
        ("hard", [one]),
        ("easy", [two]),
        ("medium", [one, two]),
    ]
    written = [await add_item(open_item(), tags(d, t), origin="generated") for d, t in bank]
    retired = await add_item(open_item(), tags("easy", [one]), origin="generated")
    await items.retire_item(retired.id)
    await settled(*written, retired)

    counts = await items.count_items(ItemFilters(curriculum_sections=[one.section, two.section]))

    assert {(c.curriculum_section, c.difficulty): c.count for c in counts} == {
        (one.section, "easy"): 2,
        (one.section, "hard"): 1,
        (one.section, "medium"): 1,
        (two.section, "easy"): 1,
        (two.section, "medium"): 1,
    }


async def test_rebuild_brings_back_an_item_whose_reindex_was_lost(monkeypatch):
    monkeypatch.setattr(get_settings(), "items_index", f"{get_settings().items_index}-rebuilt")

    async def lost(item_id):
        pass

    monkeypatch.setattr(records, "reindex_later", lost)
    topic = own_topic()
    item = await add_item(open_item(), tags(topics=[topic]), origin="generated")
    filters = ItemFilters(curriculum_topics=[topic.id])
    assert (await items.search_items("równanie", filters)).items == []

    await index.rebuild()
    await index.rebuild()

    assert (await items.search_items("równania", filters)).items == [item]
