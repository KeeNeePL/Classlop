"""Nowa praca: the form with the bank's stock, picking and swapping Items for the preview, and
giving the Assignment. Picking is `items`', giving is `teams`'; this only runs the form."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from classlop import items, teams
from classlop.dashboard import auth, bank
from classlop.items import CurriculumSection, Item, SectionCount
from classlop.items.types import Difficulty
from classlop.shared import typeset
from classlop.shared.jobs import SignInRequired
from classlop.teams.ids import as_uuid
from classlop.teams.types import AssignmentState, AssignmentType

log = logging.getLogger(__name__)
router = APIRouter()


def team_class(class_id: str) -> str:
    """The `teams` id of the Class in the URL. Until Reports read `teams` (#81) the sidebar's
    Classes are invented, so only a real Class id gets further."""
    return class_id


TeamClass = Annotated[str, Depends(team_class)]
Teacher = Annotated[auth.Me, Depends(auth.teacher)]


class StudentChoice(BaseModel):
    id: str
    name: str


class NewWorkForm(BaseModel):
    class_name: str
    sections: list[CurriculumSection]
    students: list[StudentChoice]
    # The bank's Items per section and Difficulty; `unused` leaves out those the Class got.
    stock: list[SectionCount]
    unused: list[SectionCount]


async def known_class(class_id: str) -> teams.Class:
    try:
        as_uuid(class_id)
        return await teams.get_class(class_id)
    except (LookupError, ValueError):
        raise HTTPException(404, "Nie ma takiej klasy") from None


@router.get("/api/classes/{class_id}/new-work")
async def form(class_id: TeamClass, _: Teacher, pool: bank.TheBank) -> NewWorkForm:
    klass = await known_class(class_id)
    students = [s for s in await teams.list_students(class_id) if not s.former_since]
    return NewWorkForm(
        class_name=klass.name,
        sections=items.curriculum(),
        students=[StudentChoice(id=s.id, name=s.display_name) for s in students],
        stock=await pool.stock(None),
        unused=await pool.stock(as_uuid(class_id)),
    )


class Line(BaseModel):
    """What the Teacher asked of one cell of the table: `count` Items of a Curriculum section at
    one Difficulty."""

    section: str
    difficulty: Difficulty
    count: int = Field(ge=1, le=50)


class PickRequest(BaseModel):
    lines: list[Line]
    allow_reuse: bool = False


class Placed(BaseModel):
    """A previewed Item and the cell it was picked for, which a swap draws from again."""

    section: str
    difficulty: Difficulty
    item: Item


class Shortfall(BaseModel):
    section: str
    difficulty: Difficulty
    wanted: int
    got: int


class Preview(BaseModel):
    entries: list[Placed]
    shortfalls: list[Shortfall]


def known_section(section: str) -> None:
    if section not in {s.id for s in items.curriculum()}:
        raise HTTPException(422, f"Nie ma takiego działu: {section}")


@router.post("/api/classes/{class_id}/new-work/pick")
async def pick(class_id: TeamClass, body: PickRequest, _: Teacher, pool: bank.TheBank) -> Preview:
    """The Items for the preview, line by line; no Item twice."""
    await known_class(class_id)
    entries: list[Placed] = []
    shortfalls: list[Shortfall] = []
    for wanted in body.lines:
        known_section(wanted.section)
        found = await pool.pick(
            wanted.section,
            wanted.difficulty,
            wanted.count,
            as_uuid(class_id),
            allow_reuse=body.allow_reuse,
            exclude=[e.item.id for e in entries],
        )
        entries += [
            Placed(section=wanted.section, difficulty=wanted.difficulty, item=i) for i in found
        ]
        if len(found) < wanted.count:
            shortfalls.append(
                Shortfall(
                    section=wanted.section,
                    difficulty=wanted.difficulty,
                    wanted=wanted.count,
                    got=len(found),
                )
            )
    return Preview(entries=entries, shortfalls=shortfalls)


class SwapRequest(BaseModel):
    """A previewed Item's cell, and every Item the preview holds."""

    section: str
    difficulty: Difficulty
    exclude: list[uuid.UUID]
    allow_reuse: bool = False


class Swapped(BaseModel):
    # None when the bank has no other Item for the cell.
    item: Item | None


@router.post("/api/classes/{class_id}/new-work/swap")
async def swap(class_id: TeamClass, body: SwapRequest, _: Teacher, pool: bank.TheBank) -> Swapped:
    """ "Podmień na inne": another Item of the same cell that the preview does not hold."""
    await known_class(class_id)
    known_section(body.section)
    found = await pool.pick(
        body.section,
        body.difficulty,
        1,
        as_uuid(class_id),
        allow_reuse=body.allow_reuse,
        exclude=body.exclude,
    )
    return Swapped(item=found[0] if found else None)


# What the type sets as a late default: homework closes a week after it is due, a quiz or exam
# after a 5-minute grace.
CLOSES_AFTER: dict[AssignmentType, timedelta] = {
    "homework": timedelta(days=7),
    "quiz": timedelta(minutes=5),
    "exam": timedelta(minutes=5),
}


class GiveRequest(BaseModel):
    title: str = Field(min_length=1)
    type: AssignmentType
    # In the order the Student reads them, which is the order grading numbers them in.
    item_ids: list[uuid.UUID] = Field(min_length=1)
    # None is the whole Class.
    student_ids: list[str] | None = None
    reminder_on: bool = True
    due_at: datetime
    # Given at once when missing.
    publish_at: datetime | None = None


class GivenWork(BaseModel):
    id: str
    state: AssignmentState


def items_pdf(title: str, given: list[Item]) -> bytes:
    """The Items as a sheet for the Students: numbered, with their points and options."""
    document: list[typeset.Heading | typeset.Paragraph] = [typeset.Heading(title)]
    numbers: list[int | None] = [None]
    for n, item in enumerate(given, 1):
        v = item.version
        document.append(typeset.Paragraph(f"{n}. {v.text} ({v.points} pkt)"))
        for label, text in sorted(v.options.items()):
            document.append(typeset.Paragraph(f"{label}) {text}"))
        numbers += [n] * (1 + len(v.options))
    try:
        return typeset.render(document)
    except typeset.TypesetError as error:
        where = f"Zadanie {numbers[error.block]} " if error.block else "Zadania "
        raise HTTPException(422, f"{where}nie składa się do PDF: {error}") from error


@router.post("/api/classes/{class_id}/assignments")
async def give(class_id: TeamClass, body: GiveRequest, _: Teacher, pool: bank.TheBank) -> GivenWork:
    """Give the Assignment now or at `publish_at`: `teams` posts the Items PDF and tells the
    Students, and `items` pins the Items."""
    await known_class(class_id)
    try:
        found = await pool.get_many(body.item_ids)
    except LookupError:
        raise HTTPException(404, "Nie ma takiego zadania") from None
    pdf = await asyncio.to_thread(items_pdf, body.title.strip(), found)
    spec = teams.AssignmentSpec(
        title=body.title,
        type=body.type,
        due_at=body.due_at,
        close_at=body.due_at + CLOSES_AFTER[body.type],
        item_ids=body.item_ids,
        student_ids=body.student_ids,
        reminder_on=body.reminder_on,
    )
    try:
        given = await teams.give_assignment(class_id, spec, pdf, body.publish_at)
    except SignInRequired as error:
        raise HTTPException(401) from error
    except teams.ClassReadOnly as error:
        raise HTTPException(409, "Zespół tej klasy usunięto w Teams") from error
    except ValueError as error:
        raise HTTPException(422, "Sprawdź tytuł, termin i uczniów") from error
    except Exception as error:
        log.exception("giving to %s failed", class_id)
        raise HTTPException(502, "Teams nie przyjął pracy. Spróbuj jeszcze raz.") from error
    return GivenWork(id=given.id, state=given.state)
