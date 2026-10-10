"""Generation requests against the compose stand-ins (postgres, elasticmq, opensearch, s3) loaded
with the invented Knowledge base, with a fake LLM, a fake tagger and fake embeddings."""

import asyncio
import itertools
import os
import uuid
from contextlib import suppress
from pathlib import Path

import pytest
from opensearchpy import NotFoundError
from test_items import fake_vector

from classlop import items
from classlop.items import CurriculumTopic, embedding, exemplars, generation, index, tagging
from classlop.items.generation import Draft, Ranking, Score
from classlop.items.types import Tags
from classlop.shared import jobs, llm, queue, search, storage, worker
from classlop.shared.migrate import migrate
from classlop.shared.settings import get_settings

INVENTED = Path(__file__).parent.parent / "evals/knowledge-base/invented.jsonl"
KEY = "items/knowledge-base/test-generation.jsonl"
INEQUALITY = CurriculumTopic(id="lo2024:III.3", name="Rozwiązuje nierówności liniowe")
SEQUENCE = CurriculumTopic(id="lo2024:VI.1", name="Ciągi")
CHAT = items.GenerationOrigin(kind="chat", chat_id="chat-1")


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
    # Other modules delete the indexes at their end; this one makes sure of them again.
    index._created.clear()
    exemplars._created.clear()
    storage.put(KEY, INVENTED.read_bytes(), "application/x-ndjson")
    yield
    for name in (get_settings().items_index, get_settings().exemplars_index):
        with suppress(NotFoundError):
            await search.client().indices.delete(index=name)
    index._created.clear()
    exemplars._created.clear()


class FakeLLM:
    """Rerank scores every candidate `rerank_score`; generation writes a fresh Item per call
    unless `drafts` queues others first."""

    def __init__(self, monkeypatch):
        self.rerank_score = 0.9
        self.drafts: list[Draft] = []
        self.generated = 0
        monkeypatch.setattr(llm, "ask", self.ask)

    def fresh(self, item_format="open") -> Draft:
        n = next(_counter)
        text = " ".join(f"w{n}{c}" for c in "abcdefgh")
        if item_format == "closed":
            return Draft(
                item_format="closed",
                text=text,
                points=1,
                options={"A": "$1$", "B": "$2$"},
                correct_options=["A"],
            )
        return Draft(
            item_format="open",
            text=text,
            points=1,
            answer="$1$",
            model_solution="$1$",
            rubric=[items.RubricLevel(points=1, description="Wynik.")],
        )

    async def ask(self, job, schema, messages):
        if schema is Ranking:
            ids = [c["id"] for c in __import__("json").loads(messages[1].content)["kandydaci"]]
            return Ranking(scores=[Score(id=i, score=self.rerank_score) for i in ids])
        self.generated += 1
        return self.drafts.pop(0) if self.drafts else self.fresh()


_counter = itertools.count(1)


class FakeTagger:
    """Tags every text with the next queued Tags, or `default`."""

    def __init__(self, monkeypatch):
        self.default = tags()
        self.queue: list[Tags] = []
        self.texts: list[str] = []
        monkeypatch.setattr(tagging, "default_tagger", lambda: self)

    async def tag(self, text: str) -> Tags:
        self.texts.append(text)
        return self.queue.pop(0) if self.queue else self.default


def tags(difficulty="easy", topic=INEQUALITY) -> Tags:
    return Tags(difficulty=difficulty, curriculum_topics=[topic], general_requirements=["I"])


@pytest.fixture
def fake_llm(monkeypatch):
    return FakeLLM(monkeypatch)


@pytest.fixture
def fake_tagger(monkeypatch):
    return FakeTagger(monkeypatch)


@pytest.fixture(autouse=True)
async def knowledge_base(monkeypatch):
    async def embed(texts: list[str]) -> list[list[float]]:
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(embedding, "embed", embed)
    worker.load_handlers()
    await exemplars.load(KEY)


async def run(spec: items.GenerationSpec, origin=CHAT):
    job_id = await items.request_generation(spec, origin)
    while messages := await queue.receive(wait_seconds=1):
        for message in messages:
            await jobs.process(message)
    (job,) = await jobs.get_jobs([job_id])
    return job


def spec(*lines: items.Line, **kw) -> items.GenerationSpec:
    return items.GenerationSpec(lines=list(lines), **kw)


def line(count=1, difficulty="easy", item_format="open", **kw) -> items.Line:
    return items.Line(count=count, difficulty=difficulty, item_format=item_format, **kw)


async def landed(job) -> list[items.Item]:
    ids = [uuid.UUID(i) for ids in job.result["lines"] for i in ids]
    return await items.get_items(ids)


async def test_a_request_lands_the_asked_items_in_the_bank_tagged_and_modelled(
    fake_llm, fake_tagger
):
    job = await run(spec(line(3, curriculum_topics=[INEQUALITY.id])))

    assert job.status == "succeeded", job.error
    assert [len(ids) for ids in job.result["lines"]] == [3]
    assert job.progress == {"landed": 3, "total": 3}
    bank = await landed(job)
    assert all(i.origin == "chat" and i.origin_ref == "chat-1" and not i.flagged for i in bank)
    assert all(i.version.curriculum_topics == [INEQUALITY] for i in bank)
    assert all(3 <= len(i.exemplar_ids) <= 5 for i in bank)
    page = await items.search_items("", items.Filters(origin=["chat"]))
    assert {i.id for i in bank} <= {i.id for i in page.items}


async def test_the_result_lists_item_ids_per_shortfall_line(fake_llm, fake_tagger):
    fake_tagger.default = tags("medium", SEQUENCE)
    class_id = uuid.uuid4()
    job = await run(
        spec(
            line(2, "medium", curriculum_section="lo2024:VI"),
            line(1, "medium", "closed", curriculum_section="lo2024:VI"),
        ),
        items.GenerationOrigin(kind="nowa_praca", class_id=class_id),
    )

    assert [len(ids) for ids in job.result["lines"]] == [2, 1]
    third = (await items.get_items([uuid.UUID(job.result["lines"][1][0])]))[0]
    assert third.version.item_format == "open" or third.flagged  # the fake writes open drafts
    assert third.origin == "nowa_praca" and third.origin_ref == str(class_id)


async def test_a_wrong_difficulty_regenerates_until_the_tags_match(fake_llm, fake_tagger):
    fake_tagger.queue = [tags("hard"), tags("hard")]
    job = await run(spec(line(1, "easy")))

    (item,) = await landed(job)
    assert fake_llm.generated == 3
    assert item.version.difficulty == "easy" and not item.flagged


async def test_a_named_topic_must_be_among_the_tags(fake_llm, fake_tagger):
    fake_tagger.queue = [tags(topic=SEQUENCE)]
    job = await run(spec(line(1, curriculum_topics=[INEQUALITY.id])))

    (item,) = await landed(job)
    assert fake_llm.generated == 2
    assert INEQUALITY in item.version.curriculum_topics and not item.flagged


async def test_a_shortfall_line_needs_a_tag_within_its_section(fake_llm, fake_tagger):
    fake_tagger.default = tags("medium", SEQUENCE)
    fake_tagger.queue = [tags("medium", INEQUALITY)]
    job = await run(spec(line(1, "medium", curriculum_section="lo2024:VI")))

    (item,) = await landed(job)
    assert fake_llm.generated == 2
    assert [t.id for t in item.version.curriculum_topics] == [SEQUENCE.id]


async def test_the_third_failed_attempt_enters_the_bank_flagged(fake_llm, fake_tagger):
    fake_tagger.default = tags("hard")
    job = await run(spec(line(1, "easy")))

    (item,) = await landed(job)
    assert fake_llm.generated == 3
    assert item.flagged and "trudność" in (item.flag_reason or "")


async def test_a_near_duplicate_of_a_banked_item_regenerates(fake_llm, fake_tagger):
    twin = fake_llm.fresh()
    banked = items.ItemContent(**twin.model_dump(), **tags().model_dump())
    banked_id = await items.create_item(banked, origin="upload")
    await index.reindex(banked_id)
    await search.client().indices.refresh(index=get_settings().items_index)
    fake_llm.drafts = [twin]

    job = await run(spec(line(1, "easy")))

    (item,) = await landed(job)
    assert fake_llm.generated == 2
    assert item.version.text != twin.text and not item.flagged


async def test_a_weak_rerank_flags_no_exemplar(fake_llm, fake_tagger):
    fake_llm.rerank_score = 0.1
    job = await run(spec(line(1, "easy")))

    (item,) = await landed(job)
    assert item.flagged and item.flag_reason == generation.NO_EXEMPLAR


async def test_a_batch_spreads_over_the_exemplars(fake_llm, fake_tagger):
    fake_tagger.default = tags("medium", SEQUENCE)
    # The invented bundle has six medium Exemplars in the section, so some overlap is forced.
    job = await run(spec(line(2, "medium", curriculum_section="lo2024:VI")))

    first, second = await landed(job)
    assert len(set(first.exemplar_ids) | set(second.exemplar_ids)) == 6


async def test_a_request_beyond_basic_level_is_refused(fake_llm, fake_tagger):
    with pytest.raises(ValueError, match="basic"):
        await items.request_generation(spec(line(), level="extended"), CHAT)
    assert fake_llm.generated == 0
