import uuid
from datetime import datetime
from typing import Any, TypedDict, Unpack

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from classlop.items.models import ItemRow, UsageRow, VersionRow
from classlop.items.tagging import Tagger, default_tagger
from classlop.items.types import (
    CurriculumTopic,
    Difficulty,
    GeneralRequirement,
    Item,
    ItemContent,
    ItemVersion,
    Origin,
    RubricLevel,
    TagField,
    Usage,
)
from classlop.shared.db import sessions
from classlop.shared.jobs import enqueue

TAG_FIELDS: tuple[TagField, ...] = ("difficulty", "curriculum_topics", "general_requirements")


async def _reindex(*item_ids: uuid.UUID) -> None:
    """After the commit: the search index is a copy, brought up to date by a job."""
    for item_id in item_ids:
        await enqueue("items.reindex", {"item_id": str(item_id)})


def _version(row: VersionRow) -> ItemVersion:
    return ItemVersion.model_validate(row, from_attributes=True)


def _item(row: ItemRow, version: VersionRow) -> Item:
    return Item(
        id=row.id,
        origin=row.origin,  # type: ignore[arg-type]
        origin_ref=row.origin_ref,
        source_file=row.source_file,
        source_page=row.source_page,
        exemplar_ids=row.exemplar_ids,
        flagged=row.flagged,
        flag_reason=row.flag_reason,
        retired=row.retired,
        created_at=row.created_at,
        version=_version(version),
    )


def _content(row: VersionRow) -> ItemContent:
    return ItemContent.model_validate(
        _version(row).model_dump(exclude={"id", "item_id", "number", "created_at"})
    )


async def _latest(session: AsyncSession, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, VersionRow]:
    rows = await session.scalars(
        select(VersionRow)
        .where(VersionRow.item_id.in_(item_ids))
        .ext(distinct_on(VersionRow.item_id))
        .order_by(VersionRow.item_id, VersionRow.number.desc())
    )
    return {row.item_id: row for row in rows}


async def _add_version(
    session: AsyncSession, item_id: uuid.UUID, content: ItemContent, teacher_tags: list[TagField]
) -> VersionRow:
    # Serialises writers of one Item, so version numbers never collide.
    await session.execute(select(ItemRow.id).where(ItemRow.id == item_id).with_for_update())
    number = await session.scalar(
        select(func.coalesce(func.max(VersionRow.number), 0) + 1).where(
            VersionRow.item_id == item_id
        )
    )
    row = VersionRow(
        item_id=item_id,
        number=number,
        teacher_tags=list(teacher_tags),
        **content.model_dump(mode="json"),
    )
    session.add(row)
    await session.flush()
    return row


async def create_item(
    content: ItemContent,
    *,
    origin: Origin,
    origin_ref: str | None = None,
    source_file: str | None = None,
    source_page: int | None = None,
    exemplar_ids: list[str] | None = None,
    flag_reason: str | None = None,
) -> uuid.UUID:
    """A new Item with its first version; `flag_reason` makes it a Flagged item."""
    async with sessions().begin() as session:
        row = ItemRow(
            origin=origin,
            origin_ref=origin_ref,
            source_file=source_file,
            source_page=source_page,
            exemplar_ids=exemplar_ids or [],
            flagged=flag_reason is not None,
            flag_reason=flag_reason,
        )
        session.add(row)
        await session.flush()
        await _add_version(session, row.id, content, [])
    await _reindex(row.id)
    return row.id


async def get_items(item_ids: list[uuid.UUID]) -> list[Item]:
    """The Items with their current version, in the order asked."""
    async with sessions()() as session:
        rows = {
            r.id: r for r in await session.scalars(select(ItemRow).where(ItemRow.id.in_(item_ids)))
        }
        versions = await _latest(session, item_ids)
    if missing := set(item_ids) - rows.keys():
        raise LookupError(f"no Item {sorted(missing)}")
    return [_item(rows[i], versions[i]) for i in item_ids]


async def get_versions(version_ids: list[uuid.UUID]) -> list[ItemVersion]:
    """The versions in the order asked; takes a few hundred ids in one call."""
    async with sessions()() as session:
        rows = {
            r.id: r
            for r in await session.scalars(select(VersionRow).where(VersionRow.id.in_(version_ids)))
        }
    if missing := set(version_ids) - rows.keys():
        raise LookupError(f"no version {sorted(missing)}")
    return [_version(rows[i]) for i in version_ids]


class ItemEdit(TypedDict, total=False):
    """What the Teacher can change in an Item; a tag set here survives later re-tags."""

    text: str
    points: int
    difficulty: Difficulty
    curriculum_topics: list[CurriculumTopic]
    general_requirements: list[GeneralRequirement]
    options: dict[str, str]
    correct_options: list[str]
    answer: str | None
    rubric: list[RubricLevel]
    model_solution: str | None


async def _latest_row(session: AsyncSession, item_id: uuid.UUID) -> VersionRow:
    row = (await _latest(session, [item_id])).get(item_id)
    if row is None:
        raise LookupError(f"no Item {item_id}")
    return row


async def _rewrite(
    item_id: uuid.UUID,
    changes: ItemEdit,
    tagger: Tagger | None,
    *,
    retag: bool,
    clear_flag: bool,
) -> None:
    """The next version: the current one with `changes`, re-tagged where the Teacher has not
    set the tag. The tagger runs outside the transaction."""
    async with sessions()() as session:
        current = await _latest_row(session, item_id)
    data: dict[str, Any] = {**_content(current).model_dump(), **changes}
    teacher_tags = {*current.teacher_tags, *(changes.keys() & set(TAG_FIELDS))}
    if retag or ("text" in changes and changes["text"] != current.text):
        tags = await (tagger or default_tagger()).tag(data["text"])
        data |= {f: getattr(tags, f) for f in TAG_FIELDS if f not in teacher_tags}
    content = ItemContent.model_validate(data)

    async with sessions().begin() as session:
        await session.execute(select(ItemRow.id).where(ItemRow.id == item_id).with_for_update())
        if (await _latest_row(session, item_id)).number != current.number:
            raise RuntimeError(f"Item {item_id} changed while it was being edited")
        await _add_version(session, item_id, content, [f for f in TAG_FIELDS if f in teacher_tags])
        if clear_flag:
            await session.execute(
                update(ItemRow).where(ItemRow.id == item_id).values(flagged=False, flag_reason=None)
            )
    await _reindex(item_id)


async def edit_item(
    item_id: uuid.UUID, *, tagger: Tagger | None = None, **changes: Unpack[ItemEdit]
) -> None:
    """The Teacher edits an Item: a new version, re-tagged if the text changed; it dismisses a
    flag."""
    if unknown := changes.keys() - ItemEdit.__annotations__.keys():
        raise TypeError(f"edit_item cannot change {sorted(unknown)}")
    await _rewrite(item_id, changes, tagger, retag=False, clear_flag=True)


async def retag(item_id: uuid.UUID, *, tagger: Tagger | None = None) -> None:
    """A new version of the same content with fresh tags, except those the Teacher set."""
    await _rewrite(item_id, {}, tagger, retag=True, clear_flag=False)


async def new_version(item_id: uuid.UUID, content: ItemContent) -> None:
    """A regeneration: the version the AI wrote in place of the current one. The tags the
    Teacher set stay marked, so a later re-tag still leaves them."""
    async with sessions().begin() as session:
        current = await _latest_row(session, item_id)
        await _add_version(session, item_id, content, current.teacher_tags)
    await _reindex(item_id)


async def _set(item_id: uuid.UUID, **values) -> None:
    async with sessions().begin() as session:
        found = await session.scalar(
            update(ItemRow).where(ItemRow.id == item_id).values(**values).returning(ItemRow.id)
        )
        if found is None:
            raise LookupError(f"no Item {item_id}")
    await _reindex(item_id)


async def retire_item(item_id: uuid.UUID) -> None:
    await _set(item_id, retired=True)


async def restore_item(item_id: uuid.UUID) -> None:
    await _set(item_id, retired=False)


async def dismiss_flag(item_id: uuid.UUID) -> None:
    await _set(item_id, flagged=False, flag_reason=None)


async def give(
    item_ids: list[uuid.UUID], assignment_id: uuid.UUID, class_id: uuid.UUID, given_at: datetime
) -> list[uuid.UUID]:
    """Pin the current version of each Item to the Assignment and record the usage; giving the
    same Assignment again changes nothing. Returns the version ids in the order asked."""
    async with sessions().begin() as session:
        if not item_ids:
            return []
        latest = await _latest(session, item_ids)
        if missing := set(item_ids) - latest.keys():
            raise LookupError(f"no Item {sorted(missing)}")
        await session.execute(
            insert(UsageRow)
            .values(
                [
                    dict(
                        item_id=i,
                        version_id=latest[i].id,
                        assignment_id=assignment_id,
                        class_id=class_id,
                        given_at=given_at,
                    )
                    for i in item_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["assignment_id", "item_id"])
        )
        rows = await session.execute(
            select(UsageRow.item_id, UsageRow.version_id).where(
                UsageRow.assignment_id == assignment_id, UsageRow.item_id.in_(item_ids)
            )
        )
        pinned = {item_id: version_id for item_id, version_id in rows}
    await _reindex(*item_ids)
    return [pinned[i] for i in item_ids]


async def usage(item_id: uuid.UUID) -> list[Usage]:
    """Every time the Item was Given, oldest first."""
    async with sessions()() as session:
        rows = await session.scalars(
            select(UsageRow).where(UsageRow.item_id == item_id).order_by(UsageRow.given_at)
        )
        return [Usage.model_validate(r, from_attributes=True) for r in rows]
