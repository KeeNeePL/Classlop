"""The `items` search index: a copy of Postgres that a job and `rebuild-index` keep current."""

import re
import time
import uuid
from collections.abc import Iterator
from contextlib import suppress

from opensearchpy import ConflictError, NotFoundError, RequestError
from opensearchpy.helpers import async_bulk
from sqlalchemy import select

from classlop.items import embedding
from classlop.items.models import ItemRow, UsageRow
from classlop.items.records import get_items
from classlop.items.types import Filters, ItemContent, SearchPage, SectionCount
from classlop.shared.db import sessions
from classlop.shared.search import client
from classlop.shared.settings import get_settings

DIMENSIONS = 1536  # text-embedding-ada-002
PIPELINE = "classlop-hybrid"
BATCH = 50
_created: set[str] = set()  # indexes this process has made sure of
# The nearest neighbours the vector half of a search contributes before paging.
NEIGHBOURS = 100

SETTINGS = {
    "index": {"knn": True},
    "analysis": {
        "analyzer": {
            "polish_text": {"tokenizer": "standard", "filter": ["lowercase", "polish_stem"]}
        }
    },
}
KEYWORDS = (
    "item_id",
    "version_id",
    "difficulty",
    "item_format",
    "curriculum_topics",
    "curriculum_sections",
    "general_requirements",
    "origin",
    "used_class_ids",
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
        "points": {"type": "integer"},
        "retired": {"type": "boolean"},
        "flagged": {"type": "boolean"},
        "created_at": {"type": "date"},
    }
}
# Min-max normalising both halves puts the text score and the vector score on one scale.
HYBRID_PIPELINE = {
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {"technique": "arithmetic_mean"},
            }
        }
    ]
}


def _clock() -> int:
    return time.time_ns() // 1000


def section_of(topic_id: str) -> str:
    """`lo2024:II.5` belongs to section `lo2024:II`."""
    return topic_id.rsplit(".", 1)[0]


def searchable_text(v: ItemContent) -> str:
    """The text, options and Curriculum topic wording with the LaTeX markup stripped."""
    parts = [v.text, *v.options.values(), *(t.name for t in v.curriculum_topics)]
    return re.sub(r"[\s$\\{}^_]+", " ", " ".join(parts)).strip()


async def _class_ids(item_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    async with sessions()() as session:
        rows = await session.execute(
            select(UsageRow.item_id, UsageRow.class_id)
            .where(UsageRow.item_id.in_(item_ids))
            .distinct()
        )
    used: dict[uuid.UUID, list[str]] = {}
    for item_id, class_id in rows:
        used.setdefault(item_id, []).append(str(class_id))
    return used


async def _documents(item_ids: list[uuid.UUID]) -> list[dict]:
    items = await get_items(item_ids)
    used = await _class_ids(item_ids)
    texts = [searchable_text(i.version) for i in items]
    vectors = await embedding.embed(texts)
    return [
        {
            "item_id": str(i.id),
            "version_id": str(i.version.id),
            "text": text,
            "embedding": vector,
            "difficulty": i.version.difficulty,
            "item_format": i.version.item_format,
            "points": i.version.points,
            "curriculum_topics": [t.id for t in i.version.curriculum_topics],
            "curriculum_sections": sorted({section_of(t.id) for t in i.version.curriculum_topics}),
            "general_requirements": i.version.general_requirements,
            "origin": i.origin,
            "retired": i.retired,
            "flagged": i.flagged,
            "used_class_ids": used.get(i.id, []),
            "created_at": i.created_at.isoformat(),
        }
        for i, text, vector in zip(items, texts, vectors, strict=True)
    ]


async def create_index() -> None:
    name = get_settings().items_index
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


async def reindex(item_id: uuid.UUID) -> None:
    """Write the Item's current state to the index; safe to repeat, and a job that read Postgres
    earlier never overwrites one that read it later (SQS delivers in any order)."""
    read_at = _clock()
    (document,) = await _documents([item_id])
    await create_index()
    with suppress(ConflictError):
        await client().index(
            index=get_settings().items_index,
            id=str(item_id),
            body=document,
            params={"version": read_at, "version_type": "external"},
        )


async def rebuild() -> int:
    """Drop the index and refill it from Postgres; returns the number of Items."""
    name = get_settings().items_index
    with suppress(NotFoundError):
        await client().indices.delete(index=name)
    _created.discard(name)
    await create_index()
    async with sessions()() as session:
        ids = list(await session.scalars(select(ItemRow.id).order_by(ItemRow.created_at)))
    for start in range(0, len(ids), BATCH):
        read_at = _clock()
        documents = await _documents(ids[start : start + BATCH])
        # A reindex job that ran meanwhile has a later version and wins.
        await async_bulk(
            client(),
            (
                {
                    "_index": name,
                    "_id": d["item_id"],
                    "_source": d,
                    "_version": read_at,
                    "_version_type": "external",
                }
                for d in documents
            ),
            raise_on_error=False,
        )
    await client().indices.refresh(index=name)
    return len(ids)


def _clauses(f: Filters) -> dict:
    filter_: list[dict] = []
    must_not: list[dict] = []
    for field in ("difficulty", "curriculum_topics", "curriculum_sections", "origin"):
        if values := getattr(f, field):
            filter_.append({"terms": {field: values}})
    if f.general_requirements:
        filter_.append({"terms": {"general_requirements": f.general_requirements}})
    if f.item_format:
        filter_.append({"term": {"item_format": f.item_format}})
    for field in ("retired", "flagged"):
        if (value := getattr(f, field)) is not None:
            filter_.append({"term": {field: value}})
    if f.used_with_class:
        filter_.append({"term": {"used_class_ids": str(f.used_with_class)}})
    if f.never_used_with_class:
        must_not.append({"term": {"used_class_ids": str(f.never_used_with_class)}})
    return {"filter": filter_, "must_not": must_not}


async def search_items(
    query: str, filters: Filters | None = None, page: int = 1, size: int = 20
) -> SearchPage:
    """The Items matching the words (Stempel) and the meaning (k-NN) of the query, best first;
    a blank query lists the newest Items. No rerank."""
    filters = filters or Filters()
    await create_index()
    clauses = _clauses(filters)
    start = (page - 1) * size
    if query.strip():
        knn = {
            "vector": await embedding.embed_query(query),
            "k": NEIGHBOURS,
            "filter": {"bool": clauses},
        }
        body = {
            "query": {
                "hybrid": {
                    "queries": [
                        {"bool": {"must": [{"match": {"text": query}}], **clauses}},
                        {"knn": {"embedding": knn}},
                    ],
                    "pagination_depth": NEIGHBOURS,
                }
            }
        }
        params = {"search_pipeline": PIPELINE}
    else:
        body = {"query": {"bool": clauses}, "sort": [{"created_at": "desc"}]}
        params = {}
    result = await client().search(
        index=get_settings().items_index,
        body={**body, "from": start, "size": size, "_source": ["item_id"]},
        params=params,
    )
    ids = [uuid.UUID(hit["_source"]["item_id"]) for hit in result["hits"]["hits"]]
    return SearchPage(
        items=await get_items(ids), total=result["hits"]["total"]["value"], page=page, size=size
    )


async def count_items(filters: Filters | None = None) -> list[SectionCount]:
    """Items per Curriculum section and Difficulty, for the pick in Nowa praca; an Item with
    topics in two sections counts in both."""
    await create_index()
    result = await client().search(
        index=get_settings().items_index,
        body={
            "size": 0,
            "query": {"bool": _clauses(filters or Filters())},
            "aggs": {
                "section": {
                    "terms": {"field": "curriculum_sections", "size": 100},
                    "aggs": {"difficulty": {"terms": {"field": "difficulty"}}},
                }
            },
        },
    )
    return list(_counts(result["aggregations"]["section"]["buckets"]))


def _counts(sections: list[dict]) -> Iterator[SectionCount]:
    for section in sections:
        for difficulty in section["difficulty"]["buckets"]:
            yield SectionCount(
                section=section["key"], difficulty=difficulty["key"], count=difficulty["doc_count"]
            )
