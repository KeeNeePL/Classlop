"""The Bank zadań screen: searching the Item bank, an Item's detail with its usage history, and
the Teacher's Edit, Retire/Restore and Dismiss flag. It never creates Items."""

import uuid
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from classlop import grading, items, teams
from classlop.dashboard import auth
from classlop.items import (
    CurriculumSection,
    Filters,
    GeneralRequirementText,
    Item,
    ItemEdit,
    RubricLevel,
    SearchPage,
    SectionCount,
    Tagger,
)
from classlop.items.types import Difficulty, GeneralRequirement, ItemFormat
from classlop.teams.ids import as_uuid, from_uuid

router = APIRouter()

# What the Model solution depends on: after an edit of these the AI offers to write it again.
SOLUTION_INPUTS = frozenset({"text", "points", "answer", "rubric", "options", "correct_options"})


class UsageEntry(BaseModel):
    """An Item Given to a Class in an Assignment, with how the Class did on it. The title and
    name are missing when `teams` no longer knows the Assignment or the Class."""

    assignment_id: str
    title: str | None
    class_id: str
    class_name: str | None
    given_at: datetime
    # 0 to 1; missing while nothing is graded.
    average: float | None


class ItemDetail(BaseModel):
    item: Item
    usage: list[UsageEntry]


class ClassOption(BaseModel):
    id: uuid.UUID
    name: str


class BankFilters(BaseModel):
    """What the screen offers to filter and tag by: the Curriculum, the General requirements and the
    Classes."""

    sections: list[CurriculumSection]
    general_requirements: list[GeneralRequirementText]
    classes: list[ClassOption]


class ItemChanges(BaseModel):
    """What the Teacher changed; what is left out stays as it was."""

    text: str | None = None
    points: int | None = Field(default=None, ge=0)
    difficulty: Difficulty | None = None
    curriculum_topic_ids: list[str] | None = None
    general_requirements: list[GeneralRequirement] | None = None
    options: dict[str, str] | None = None
    correct_options: list[str] | None = None
    answer: str | None = None
    rubric: list[RubricLevel] | None = None
    model_solution: str | None = None


class EditResult(BaseModel):
    detail: ItemDetail
    # The Item has a Model solution the edit may have made stale: the AI offers to write it again.
    offer_regenerate: bool


class Bank(Protocol):
    """What the screen needs of the areas; tests and the Playwright server swap it."""

    async def search(self, query: str, filters: Filters, page: int, size: int) -> SearchPage: ...
    async def get(self, item_id: uuid.UUID) -> Item: ...
    async def usage(self, item_id: uuid.UUID) -> list[UsageEntry]: ...
    async def classes(self) -> list[ClassOption]: ...
    async def edit(self, item_id: uuid.UUID, changes: ItemEdit) -> None: ...
    async def retire(self, item_id: uuid.UUID) -> None: ...
    async def restore(self, item_id: uuid.UUID) -> None: ...
    async def dismiss_flag(self, item_id: uuid.UUID) -> None: ...
    async def get_many(self, item_ids: list[uuid.UUID]) -> list[Item]: ...
    async def stock(self, never_used_with: uuid.UUID | None) -> list[SectionCount]: ...
    async def pick(
        self,
        section: str,
        difficulty: Difficulty,
        n: int,
        class_id: uuid.UUID,
        *,
        allow_reuse: bool,
        exclude: list[uuid.UUID],
    ) -> list[Item]: ...


class ItemsBank:
    """The bank over `items`, with usage joined from `teams` and `grading`."""

    def __init__(self, tagger: Tagger | None = None):
        self._tagger = tagger

    async def search(self, query: str, filters: Filters, page: int, size: int) -> SearchPage:
        return await items.search_items(query, filters, page, size)

    async def get(self, item_id: uuid.UUID) -> Item:
        (item,) = await items.get_items([item_id])
        return item

    async def usage(self, item_id: uuid.UUID) -> list[UsageEntry]:
        given = await items.usage(item_id)
        averages = await grading.item_averages(list({u.assignment_id for u in given}))
        titles: dict[uuid.UUID, str | None] = {}
        names: dict[uuid.UUID, str | None] = {}
        for u in given:
            if u.assignment_id not in titles:
                titles[u.assignment_id] = await _or_none(
                    teams.get_assignment(from_uuid(u.assignment_id)), "title"
                )
            if u.class_id not in names:
                names[u.class_id] = await _or_none(teams.get_class(from_uuid(u.class_id)), "name")
        return [
            UsageEntry(
                assignment_id=from_uuid(u.assignment_id),
                title=titles[u.assignment_id],
                class_id=from_uuid(u.class_id),
                class_name=names[u.class_id],
                given_at=u.given_at,
                average=averages.get((u.assignment_id, item_id)),
            )
            for u in given
        ]

    async def classes(self) -> list[ClassOption]:
        return [ClassOption(id=as_uuid(c.id), name=c.name) for c in await teams.list_classes()]

    async def edit(self, item_id: uuid.UUID, changes: ItemEdit) -> None:
        await items.edit_item(item_id, tagger=self._tagger, **changes)

    async def retire(self, item_id: uuid.UUID) -> None:
        await items.retire_item(item_id)

    async def restore(self, item_id: uuid.UUID) -> None:
        await items.restore_item(item_id)

    async def dismiss_flag(self, item_id: uuid.UUID) -> None:
        await items.dismiss_flag(item_id)

    async def get_many(self, item_ids: list[uuid.UUID]) -> list[Item]:
        return await items.get_items(item_ids)

    async def stock(self, never_used_with: uuid.UUID | None) -> list[SectionCount]:
        return await items.count_items(Filters(never_used_with_class=never_used_with))

    async def pick(
        self,
        section: str,
        difficulty: Difficulty,
        n: int,
        class_id: uuid.UUID,
        *,
        allow_reuse: bool,
        exclude: list[uuid.UUID],
    ) -> list[Item]:
        return await items.pick_items(
            section, difficulty, n, class_id, allow_reuse=allow_reuse, exclude=exclude
        )


async def _or_none(lookup: Awaitable[Any], field: str) -> str | None:
    """A field of what `teams` returns; nothing where it no longer knows the Assignment or Class."""
    try:
        return getattr(await lookup, field)
    except LookupError:
        return None


def backend() -> Bank:
    return ItemsBank()


async def flagged_count(bank: Bank) -> int:
    """The sidebar's Flagged item count; Retired items are not counted."""
    return (await bank.search("", Filters(flagged=True), 1, 1)).total


@contextmanager
def refusing() -> Iterator[None]:
    try:
        yield
    except LookupError:
        raise HTTPException(404, "Nie ma takiego zadania") from None
    except ValidationError as error:
        raise HTTPException(422, "; ".join(e["msg"] for e in error.errors())) from None
    except RuntimeError as error:
        raise HTTPException(409, "Zadanie zmieniono w międzyczasie") from error


TheBank = Annotated[Bank, Depends(backend)]
Teacher = Annotated[auth.Me, Depends(auth.teacher)]


async def _detail(bank: Bank, item_id: uuid.UUID) -> ItemDetail:
    return ItemDetail(item=await bank.get(item_id), usage=await bank.usage(item_id))


@router.get("/api/bank/filters")
async def filters(_: Teacher, bank: TheBank) -> BankFilters:
    return BankFilters(
        sections=items.curriculum(),
        general_requirements=items.general_requirements(),
        classes=await bank.classes(),
    )


@router.get("/api/bank/items")
async def search(
    _: Teacher,
    bank: TheBank,
    q: str = "",
    topic: Annotated[list[str] | None, Query()] = None,
    section: Annotated[list[str] | None, Query()] = None,
    difficulty: Annotated[list[Difficulty] | None, Query()] = None,
    item_format: ItemFormat | None = None,
    flagged: bool | None = None,
    show_retired: bool = False,
    never_used_with_class: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchPage:
    """Retired items are left out unless `show_retired`."""
    found = Filters(
        curriculum_topics=topic or [],
        curriculum_sections=section or [],
        difficulty=difficulty or [],
        item_format=item_format,
        flagged=flagged,
        retired=None if show_retired else False,
        never_used_with_class=never_used_with_class,
    )
    return await bank.search(q, found, page, size)


@router.get("/api/bank/items/{item_id}")
async def detail(item_id: uuid.UUID, _: Teacher, bank: TheBank) -> ItemDetail:
    with refusing():
        return await _detail(bank, item_id)


@router.patch("/api/bank/items/{item_id}")
async def edit(item_id: uuid.UUID, body: ItemChanges, _: Teacher, bank: TheBank) -> EditResult:
    """A new version of the Item; it dismisses the Item's flag."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Nic do zmiany")
    if (ids := changes.pop("curriculum_topic_ids", None)) is not None:
        known = {t.id: t for s in items.curriculum() for t in s.topics}
        if unknown := [i for i in ids if i not in known]:
            raise HTTPException(422, f"Nie ma takiego tematu: {unknown[0]}")
        changes["curriculum_topics"] = [known[i] for i in ids]
    with refusing():
        await bank.edit(item_id, changes)  # type: ignore[arg-type]
        fresh = await _detail(bank, item_id)
    offer = (
        fresh.item.version.model_solution is not None
        and "model_solution" not in changes
        and bool(changes.keys() & SOLUTION_INPUTS)
    )
    return EditResult(detail=fresh, offer_regenerate=offer)


@router.post("/api/bank/items/{item_id}/retire")
async def retire(item_id: uuid.UUID, _: Teacher, bank: TheBank) -> ItemDetail:
    with refusing():
        await bank.retire(item_id)
        return await _detail(bank, item_id)


@router.post("/api/bank/items/{item_id}/restore")
async def restore(item_id: uuid.UUID, _: Teacher, bank: TheBank) -> ItemDetail:
    with refusing():
        await bank.restore(item_id)
        return await _detail(bank, item_id)


@router.post("/api/bank/items/{item_id}/dismiss-flag")
async def dismiss_flag(item_id: uuid.UUID, _: Teacher, bank: TheBank) -> ItemDetail:
    with refusing():
        await bank.dismiss_flag(item_id)
        return await _detail(bank, item_id)
