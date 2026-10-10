"""The Knowledge base load against the compose stand-ins, with fake embeddings."""

import asyncio
import os
from contextlib import suppress
from pathlib import Path

import pytest
from opensearchpy import NotFoundError
from sqlalchemy import func, select
from test_items import fake_vector

from classlop.items import embedding, exemplars
from classlop.items.models import ExemplarRow
from classlop.shared import jobs, queue, search, storage, worker
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.settings import get_settings

INVENTED = Path(__file__).parent.parent / "evals/knowledge-base/invented.jsonl"
KEY = "items/knowledge-base/test-invented.jsonl"


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
    yield
    with suppress(NotFoundError):
        await search.client().indices.delete(index=get_settings().exemplars_index)


@pytest.fixture
def fake_embeddings(monkeypatch):
    async def embed(texts: list[str]) -> list[list[float]]:
        return [fake_vector(t) for t in texts]

    monkeypatch.setattr(embedding, "embed", embed)


async def load(key: str = KEY) -> None:
    job_id = await jobs.enqueue("items.load_knowledge_base", {"key": key})
    worker.load_handlers()
    while messages := await queue.receive(wait_seconds=1):
        for message in messages:
            await jobs.process(message)
    (job,) = await jobs.get_jobs([job_id])
    assert job.status == "succeeded", job.error


async def stored() -> int:
    async with sessions()() as session:
        return await session.scalar(select(func.count()).select_from(ExemplarRow)) or 0


async def test_the_invented_bundle_loads_and_is_searchable(fake_embeddings):
    storage.put(KEY, INVENTED.read_bytes(), "application/x-ndjson")
    await load()
    assert await stored() >= 28

    found = await exemplars.search_exemplars("nierówność liniowa")
    assert found and "nierówność" in found[0].text
    assert found[0].curriculum_topics

    sections = await exemplars.search_exemplars("ciąg", curriculum_sections=["lo2024:VI"])
    assert sections and all(
        t.id.startswith("lo2024:VI.") for e in sections for t in e.curriculum_topics
    )


async def test_loading_the_same_bundle_twice_changes_nothing(fake_embeddings):
    storage.put(KEY, INVENTED.read_bytes(), "application/x-ndjson")
    await load()
    before = await stored()
    await load()
    assert await stored() == before
    await search.client().indices.refresh(index=get_settings().exemplars_index)
    count = await search.client().count(index=get_settings().exemplars_index)
    assert count["count"] == before
