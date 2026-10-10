"""The `items` OpenSearch index: a copy of the records, rebuilt from Postgres at will (ADR 0004).
The name in settings is an alias over one concrete index, so a rebuild swaps it whole."""

import re
import uuid

from opensearchpy import NotFoundError, RequestError
from opensearchpy.helpers import async_bulk
from ulid import ULID

from classlop.items import records
from classlop.items.types import Count, Item, ItemFilters, SearchPage
from classlop.shared import llm, search
from classlop.shared.settings import get_settings

# ada-002
DIMENSIONS = 1536
PAGE_SIZE = 20
# Nearest Items by meaning that join the matches by words.
MEANING_K = 10
# Hits each half of a hybrid query collects for paging.
PAGINATION_DEPTH = 200
PIPELINE = "items-hybrid"
KEYWORDS = (
    "item_format",
    "difficulty",
    "curriculum_topics",
    "curriculum_sections",
    "general_requirements",
    "origin",
    "used_class_ids",
)
MAPPING = {
    "settings": {"index": {"knn": True}},
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "version_id": {"type": "keyword"},
            "text": {"type": "text", "analyzer": "polish"},
            "embedding": {
                "type": "knn_vector",
                "dimension": DIMENSIONS,
                "method": {"name": "hnsw", "engine": "lucene", "space_type": "cosinesimil"},
            },
            **{k: {"type": "keyword"} for k in KEYWORDS},
            "flagged": {"type": "boolean"},
            "retired": {"type": "boolean"},
            "created_at": {"type": "date"},
        },
    },
}


def alias() -> str:
    return get_settings().items_index


async def reindex(item_id: uuid.UUID) -> None:
    """Writes the Item's document as Postgres has it now; safe to run any number of times."""
    await _ensure_index()
    client = search.client()
    found = await records.get_items([item_id])
    if not found:
        try:
            await client.delete(index=alias(), id=str(item_id))
        except NotFoundError:
            pass
        return
    (item,) = found
    try:
        indexed = await client.get(
            index=alias(), id=str(item_id), params={"_source_includes": "version_id,embedding"}
        )
        source = indexed["_source"]
    except NotFoundError:
        source = {}
    if source.get("version_id") == str(item.version.id):
        embedding = source["embedding"]
    else:
        embedding = await llm.embeddings().aembed_query(item.version.text)
    used = (await records.used_class_ids([item_id])).get(item_id, set())
    await client.index(index=alias(), id=str(item_id), body=_document(item, embedding, used))


async def rebuild() -> int:
    """Builds a fresh index from every record, then points the alias at it."""
    client = search.client()
    await _put_pipeline()
    fresh = f"{alias()}-{str(ULID()).lower()}"
    await client.indices.create(index=fresh, body=MAPPING)
    try:
        written = await _fill(fresh)
    except BaseException:
        await client.indices.delete(index=fresh)
        raise
    old = list(await client.indices.get_alias(name=alias())) if await _exists() else []
    swap = [{"remove": {"index": o, "alias": alias()}} for o in old]
    await client.indices.update_aliases(
        body={"actions": [*swap, {"add": {"index": fresh, "alias": alias()}}]}
    )
    for o in old:
        await client.indices.delete(index=o)
    return written


async def _fill(index: str) -> int:
    client, written = search.client(), 0
    async for batch in records.all_items():
        embeddings = await llm.embeddings().aembed_documents([i.version.text for i in batch])
        used = await records.used_class_ids([i.id for i in batch])
        actions = [
            {"_index": index, "_id": str(i.id), "_source": _document(i, e, used.get(i.id, set()))}
            for i, e in zip(batch, embeddings, strict=True)
        ]
        await async_bulk(client, actions)
        written += len(actions)
    await client.indices.refresh(index=index)
    return written


async def search_items(query: str, filters: ItemFilters | None = None, page: int = 0) -> SearchPage:
    """By words (Polish, any inflection) and by meaning; an empty query lists the newest."""
    await _ensure_index()
    where = _where(filters or ItemFilters())
    params = {}
    if query.strip():
        vector = await llm.embeddings().aembed_query(query)
        knn = {"vector": vector, "k": MEANING_K, "filter": where}
        body: dict = {
            "query": {
                "hybrid": {
                    "pagination_depth": PAGINATION_DEPTH,
                    "queries": [
                        {"bool": {"must": {"match": {"text": query}}, "filter": where}},
                        {"knn": {"embedding": knn}},
                    ],
                }
            }
        }
        params["search_pipeline"] = PIPELINE
    else:
        body = {"query": where, "sort": [{"created_at": "desc"}]}
    body |= {"from": page * PAGE_SIZE, "size": PAGE_SIZE, "_source": False}
    hits = (await search.client().search(index=alias(), body=body, params=params))["hits"]
    found = await records.get_items(uuid.UUID(h["_id"]) for h in hits["hits"])
    return SearchPage(items=found, total=hits["total"]["value"], page=page)


async def count_items(filters: ItemFilters | None = None) -> list[Count]:
    """Items per Curriculum section and Difficulty; an Item counts in each of its sections."""
    await _ensure_index()
    body = {
        "size": 0,
        "query": _where(filters or ItemFilters()),
        "aggs": {
            "sections": {
                "terms": {"field": "curriculum_sections", "size": 100},
                "aggs": {"difficulty": {"terms": {"field": "difficulty"}}},
            }
        },
    }
    response = await search.client().search(index=alias(), body=body)
    return [
        Count(curriculum_section=s["key"], difficulty=d["key"], count=d["doc_count"])
        for s in response["aggregations"]["sections"]["buckets"]
        for d in s["difficulty"]["buckets"]
    ]


def _where(f: ItemFilters) -> dict:
    terms: list[dict] = [{"term": {"retired": f.retired}}]
    for field in ("curriculum_topics", "curriculum_sections", "general_requirements", "difficulty"):
        if values := getattr(f, field):
            terms.append({"terms": {field: values}})
    for field in ("item_format", "flagged", "origin"):
        if (value := getattr(f, field)) is not None:
            terms.append({"term": {field: value}})
    unused = [{"term": {"used_class_ids": f.never_used_with_class}}]
    return {"bool": {"filter": terms, "must_not": unused if f.never_used_with_class else []}}


def _document(item: Item, embedding: list[float], used_class_ids: set[str]) -> dict:
    v = item.version
    topics = v.curriculum_topics
    return {
        "version_id": str(v.id),
        "text": " ".join(
            [_plain(v.text), *map(_plain, v.options.values()), *(t.name for t in topics)]
        ),
        "embedding": embedding,
        "item_format": v.item_format,
        "difficulty": v.difficulty,
        "curriculum_topics": [t.id for t in topics],
        "curriculum_sections": sorted({t.section for t in topics}),
        "general_requirements": v.general_requirements,
        "origin": item.origin,
        "used_class_ids": sorted(used_class_ids),
        "flagged": item.flag is not None,
        "retired": item.retired,
        "created_at": item.created_at.isoformat(),
    }


def _plain(latex: str) -> str:
    """Words for the Stempel analyzer: LaTeX commands and markup out, numbers and words kept."""
    return re.sub(r"\\[a-zA-Z]+|[\\$^_{}]", " ", latex)


async def _exists() -> bool:
    return await search.client().indices.exists_alias(name=alias())


async def _ensure_index() -> None:
    if await _exists():
        return
    await _put_pipeline()
    try:
        await search.client().indices.create(
            index=f"{alias()}-0", body=MAPPING | {"aliases": {alias(): {}}}
        )
    except RequestError as e:
        if e.error != "resource_already_exists_exception":
            raise


async def _put_pipeline() -> None:
    await search.client().transport.perform_request(
        "PUT",
        f"/_search/pipeline/{PIPELINE}",
        body={
            "phase_results_processors": [
                {
                    "normalization-processor": {
                        "normalization": {"technique": "min_max"},
                        "combination": {"technique": "arithmetic_mean"},
                    }
                }
            ]
        },
    )
