"""Item records in Postgres. Every write commits, then enqueues `items.reindex` for the Item."""

import uuid
from collections.abc import AsyncIterator, Iterable
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from classlop.items import tagging
from classlop.items.models import ItemRecord, UsageRecord, VersionRecord
from classlop.items.types import (
    CurriculumTopic,
    Difficulty,
    Flag,
    GeneralRequirement,
    Item,
    ItemContent,
    ItemVersion,
    Origin,
    Tags,
    Usage,
)
from classlop.shared import jobs
from classlop.shared.db import sessions


async def add_item(
    content: ItemContent,
    tags: Tags,
    *,
    origin: Origin,
    source_key: str | None = None,
    source_page: int | None = None,
    exemplar_ids: Iterable[str] = (),
    flag: Flag | None = None,
) -> Item:
    item_id = uuid.uuid4()
    async with sessions().begin() as session:
        session.add(
            ItemRecord(
                id=item_id,
                origin=origin,
                source_key=source_key,
                source_page=source_page,
                exemplar_ids=list(exemplar_ids),
                flag=flag,
            )
        )
        await session.flush()
        session.add(_version(item_id, 1, content, tags, teacher_tags=[]))
    return await _written(item_id)


async def edit_item(
    item_id: uuid.UUID,
    content: ItemContent,
    *,
    difficulty: Difficulty | None = None,
    curriculum_topics: list[CurriculumTopic] | None = None,
    general_requirements: list[GeneralRequirement] | None = None,
) -> Item:
    """The Teacher's edit: re-tagged, except for the tags the Teacher sets here or set before.
    Clears the flag."""
    given = {
        "difficulty": difficulty,
        "curriculum_topics": curriculum_topics,
        "general_requirements": general_requirements,
    }
    teacher_set = {k: v for k, v in given.items() if v is not None}
    return await _add_version(
        item_id, content, await tagging.tag(content), teacher_set, unflag=True
    )


async def retag_item(item_id: uuid.UUID) -> Item:
    (item,) = await get_items([item_id])
    content = ItemContent.model_validate(item.version.model_dump())
    return await _add_version(item_id, content, await tagging.tag(content), {})


async def revise_item(item_id: uuid.UUID, content: ItemContent, tags: Tags) -> Item:
    """A regeneration of the Item, tagged by the graph that made it."""
    return await _add_version(item_id, content, tags, {})


async def retire_item(item_id: uuid.UUID) -> Item:
    return await _set_state(item_id, retired_at=func.now())


async def restore_item(item_id: uuid.UUID) -> Item:
    return await _set_state(item_id, retired_at=None)


async def dismiss_flag(item_id: uuid.UUID) -> Item:
    return await _set_state(item_id, flag=None)


async def give(
    item_ids: Iterable[uuid.UUID], assignment_id: uuid.UUID, class_id: str, given_at: datetime
) -> list[uuid.UUID]:
    """Pins each Item's current version to the Assignment and returns the version ids in the
    order given; a retry returns what was pinned the first time."""
    ids = list(item_ids)
    async with sessions().begin() as session:
        current = await _current_versions(session, ids)
        rows = [
            {
                "assignment_id": assignment_id,
                "item_id": i,
                "version_id": current[i].id,
                "class_id": class_id,
                "given_at": given_at,
            }
            for i in ids
        ]
        await session.execute(insert(UsageRecord).values(rows).on_conflict_do_nothing())
        pinned = await session.execute(
            select(UsageRecord.item_id, UsageRecord.version_id).where(
                UsageRecord.assignment_id == assignment_id
            )
        )
    by_item = dict(pinned.all())
    for i in ids:
        await reindex_later(i)
    return [by_item[i] for i in ids]


async def usage(item_id: uuid.UUID) -> list[Usage]:
    async with sessions()() as session:
        rows = await session.scalars(
            select(UsageRecord).where(UsageRecord.item_id == item_id).order_by(UsageRecord.given_at)
        )
        return [Usage.model_validate(r, from_attributes=True) for r in rows]


async def get_items(item_ids: Iterable[uuid.UUID]) -> list[Item]:
    """In the order asked for; unknown ids are left out."""
    ids = list(item_ids)
    async with sessions()() as session:
        records = {
            r.id: r for r in await session.scalars(select(ItemRecord).where(ItemRecord.id.in_(ids)))
        }
        current = await _current_versions(session, ids)
    return [_item(records[i], current[i]) for i in ids if i in records]


async def get_versions(version_ids: Iterable[uuid.UUID]) -> list[ItemVersion]:
    """In the order asked for; any number of ids in one call."""
    ids = list(version_ids)
    async with sessions()() as session:
        found = {
            v.id: v
            for v in await session.scalars(select(VersionRecord).where(VersionRecord.id.in_(ids)))
        }
    return [_contract(found[i]) for i in ids]


async def all_items() -> AsyncIterator[list[Item]]:
    """Every Item, a hundred at a time."""
    async with sessions()() as session:
        ids = list(await session.scalars(select(ItemRecord.id).order_by(ItemRecord.created_at)))
    for start in range(0, len(ids), 100):
        yield await get_items(ids[start : start + 100])


async def used_class_ids(item_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
    async with sessions()() as session:
        rows = await session.execute(
            select(UsageRecord.item_id, UsageRecord.class_id).where(
                UsageRecord.item_id.in_(list(item_ids))
            )
        )
    used: dict[uuid.UUID, set[str]] = {}
    for item_id, class_id in rows:
        used.setdefault(item_id, set()).add(class_id)
    return used


async def reindex_later(item_id: uuid.UUID) -> None:
    await jobs.enqueue("items.reindex", {"item_id": str(item_id)})


async def _written(item_id: uuid.UUID) -> Item:
    await reindex_later(item_id)
    (item,) = await get_items([item_id])
    return item


async def _set_state(item_id: uuid.UUID, **values) -> Item:
    async with sessions().begin() as session:
        await session.execute(update(ItemRecord).where(ItemRecord.id == item_id).values(**values))
    return await _written(item_id)


async def _add_version(
    item_id: uuid.UUID, content: ItemContent, tags: Tags, teacher_set: dict, *, unflag: bool = False
) -> Item:
    async with sessions().begin() as session:
        previous = (await _current_versions(session, [item_id]))[item_id]
        kept = {f: getattr(previous, f) for f in previous.teacher_tags if f not in teacher_set}
        tags = Tags.model_validate(tags.model_dump() | kept | teacher_set)
        teacher_tags = sorted({*previous.teacher_tags, *teacher_set})
        session.add(_version(item_id, previous.number + 1, content, tags, teacher_tags))
        if unflag:
            await session.execute(
                update(ItemRecord).where(ItemRecord.id == item_id).values(flag=None)
            )
    return await _written(item_id)


async def _current_versions(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VersionRecord]:
    rows = await session.scalars(
        select(VersionRecord)
        .where(VersionRecord.item_id.in_(item_ids))
        .ext(distinct_on(VersionRecord.item_id))
        .order_by(VersionRecord.item_id, VersionRecord.number.desc())
    )
    return {v.item_id: v for v in rows}


def _version(
    item_id: uuid.UUID, number: int, content: ItemContent, tags: Tags, teacher_tags: list[str]
) -> VersionRecord:
    return VersionRecord(
        id=uuid.uuid4(),
        item_id=item_id,
        number=number,
        **content.model_dump(mode="json"),
        difficulty=tags.difficulty,
        curriculum_topics=[t.model_dump() for t in tags.curriculum_topics],
        general_requirements=list(tags.general_requirements),
        tag_probabilities=tags.probabilities,
        teacher_tags=teacher_tags,
    )


def _contract(v: VersionRecord) -> ItemVersion:
    return ItemVersion.model_validate(v, from_attributes=True)


def _item(record: ItemRecord, version: VersionRecord) -> Item:
    return Item(
        id=record.id,
        version=_contract(version),
        origin=record.origin,  # type: ignore[arg-type]
        source_key=record.source_key,
        source_page=record.source_page,
        exemplar_ids=record.exemplar_ids,
        flag=record.flag,  # type: ignore[arg-type]
        retired=record.retired_at is not None,
        created_at=record.created_at,
    )
