"""The Knowledge base: Exemplars in a JSONL bundle (one per line, in S3 under
`items/knowledge-base/`), upserted into `items.exemplar` and indexed into `exemplars`. A load is
idempotent: an Exemplar's id is its key in Postgres and its document id in the index."""

from pathlib import Path

from opensearchpy import RequestError
from opensearchpy.helpers import async_bulk
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from classlop.items import embedding
from classlop.items.index import (
    DIMENSIONS,
    HYBRID_PIPELINE,
    NEIGHBOURS,
    PIPELINE,
    SETTINGS,
    section_of,
)
from classlop.items.models import ExemplarRow
from classlop.items.types import Difficulty, Tags
from classlop.shared import storage
from classlop.shared.db import sessions
from classlop.shared.jobs import enqueue
from classlop.shared.search import client
from classlop.shared.settings import get_settings

BATCH = 50
KEYWORDS = (
    "difficulty",
    "curriculum_topics",
    "curriculum_sections",
    "general_requirements",
    "source",
)
MAPPINGS = {
    "properties": {
        **{name: {"type": "keyword"} for name in KEYWORDS},
        "text": {"type": "text", "analyzer": "polish_text"},
        "embedding": {
            "type": "knn_vector",
            "dimension": DIMENSIONS,
            "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "lucene"},
        },
    }
}
_created: set[str] = set()


class Exemplar(Tags):
    """One line of a bundle. A bundle may leave the embedding out; the load fills it in."""

    id: str
    source: str
    text: str
    answer: str | None = None
    solution: str | None = None
    source_tags: dict = {}
    embedding: list[float] | None = None


def parse_bundle(body: bytes) -> list[Exemplar]:
    return [
        Exemplar.model_validate_json(line) for line in body.decode("utf-8").splitlines() if line
    ]


async def create_index() -> None:
    name = get_settings().exemplars_index
    if name in _created:
        return
    try:
        await client().indices.create(index=name, body={"settings": SETTINGS, "mappings": MAPPINGS})
    except RequestError as error:
        if error.error != "resource_already_exists_exception":
            raise
    await client().transport.perform_request(
        "PUT", f"/_search/pipeline/{PIPELINE}", body=HYBRID_PIPELINE
    )
    _created.add(name)


def _document(e: Exemplar) -> dict:
    return {
        "text": e.text,
        "embedding": e.embedding,
        "source": e.source,
        "difficulty": e.difficulty,
        "curriculum_topics": [t.id for t in e.curriculum_topics],
        "curriculum_sections": sorted({section_of(t.id) for t in e.curriculum_topics}),
        "general_requirements": e.general_requirements,
    }


async def upload(bundle: Path) -> str:
    """Put a bundle under `items/knowledge-base/` and queue its load; returns the key."""
    key = f"items/knowledge-base/{bundle.name}"
    storage.put(key, bundle.read_bytes(), "application/x-ndjson")
    await enqueue("items.load_knowledge_base", {"key": key})
    return key


async def load(key: str) -> int:
    """Load the bundle at `key`; returns the number of Exemplars."""
    bundle = parse_bundle(storage.get(key))
    missing = [e for e in bundle if e.embedding is None]
    vectors = await embedding.embed([e.text for e in missing])
    for e, vector in zip(missing, vectors, strict=True):
        e.embedding = vector
    await create_index()
    for start in range(0, len(bundle), BATCH):
        chunk = bundle[start : start + BATCH]
        rows = [e.model_dump() for e in chunk]
        async with sessions().begin() as session:
            stmt = insert(ExemplarRow).values(rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={c: stmt.excluded[c] for c in rows[0] if c != "id"},
                )
            )
        await async_bulk(
            client(),
            (
                {"_index": get_settings().exemplars_index, "_id": e.id, "_source": _document(e)}
                for e in chunk
            ),
        )
    await client().indices.refresh(index=get_settings().exemplars_index)
    return len(bundle)


async def search_exemplars(
    query: str,
    *,
    curriculum_sections: list[str] | None = None,
    difficulty: list[Difficulty] | None = None,
    size: int = 5,
) -> list[Exemplar]:
    """The Exemplars matching the words (Stempel) and the meaning (k-NN) of the query, best
    first."""
    await create_index()
    filter_: list[dict] = []
    if curriculum_sections:
        filter_.append({"terms": {"curriculum_sections": curriculum_sections}})
    if difficulty:
        filter_.append({"terms": {"difficulty": difficulty}})
    knn = {
        "vector": await embedding.embed_query(query),
        "k": NEIGHBOURS,
        "filter": {"bool": {"filter": filter_}},
    }
    result = await client().search(
        index=get_settings().exemplars_index,
        body={
            "query": {
                "hybrid": {
                    "queries": [
                        {"bool": {"must": [{"match": {"text": query}}], "filter": filter_}},
                        {"knn": {"embedding": knn}},
                    ],
                    "pagination_depth": NEIGHBOURS,
                }
            },
            "size": size,
            "_source": False,
        },
        params={"search_pipeline": PIPELINE},
    )
    ids = [hit["_id"] for hit in result["hits"]["hits"]]
    async with sessions()() as session:
        rows = {
            r.id: r
            for r in await session.scalars(select(ExemplarRow).where(ExemplarRow.id.in_(ids)))
        }
    # A hit the load has not yet written to Postgres is left out.
    return [Exemplar.model_validate(rows[i], from_attributes=True) for i in ids if i in rows]
