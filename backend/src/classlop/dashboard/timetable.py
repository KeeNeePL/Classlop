"""The Timetable in Ustawienia klasy: weekly slots and the school-year end entered once, breaks and
mid-year slot changes. `teams` writes each change to Teams; the upcoming Lessons let the screen
show which ones a change will affect before the Teacher confirms."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, model_validator

from classlop import teams
from classlop.dashboard.actions import carry_out, refusing
from classlop.dashboard.classes import Teacher, TheTeams

router = APIRouter()

WARSAW = ZoneInfo("Europe/Warsaw")


def today() -> date:
    return datetime.now(WARSAW).date()


def from_today(day: date) -> None:
    """Past Lessons keep their state: a change the screen could not preview is refused."""
    if day < today():
        raise HTTPException(422, "a change starts today at the earliest")


class UpcomingLesson(BaseModel):
    id: str
    start: datetime
    end: datetime
    topic: str | None
    cancelled: bool


class Timetable(BaseModel):
    school_year_end: date | None
    slots: list[teams.Slot]
    # From today on, by start: the Lessons a break or a slot change can affect.
    lessons: list[UpcomingLesson]


class WeeklySlot(BaseModel):
    """A slot as the Teacher enters it; weekday 0 is Monday, times are Warsaw wall-clock."""

    weekday: int = Field(ge=0, le=6)
    start: time
    end: time

    @model_validator(mode="after")
    def ends_after_start(self) -> "WeeklySlot":
        if self.end <= self.start:
            raise ValueError("a slot ends after it starts")
        return self

    def slot(self) -> teams.Slot:
        return teams.Slot(**self.model_dump())


class NewTimetable(BaseModel):
    slots: list[WeeklySlot] = Field(min_length=1)
    school_year_end: date


@router.get("/api/classes/{class_id}/timetable")
async def timetable(class_id: str, _: Teacher, t: TheTeams) -> Timetable:
    with refusing():
        klass = await t.get_class(class_id)
        slots = await t.list_slots(class_id)
        lessons = await t.list_lessons(class_id)
    return Timetable(
        school_year_end=klass.school_year_end,
        slots=slots,
        lessons=[
            UpcomingLesson(**x.model_dump())
            for x in sorted(lessons, key=lambda x: x.start)
            if x.start.astimezone(WARSAW).date() >= today()
        ],
    )


@router.post("/api/classes/{class_id}/timetable", status_code=204)
async def enter_timetable(class_id: str, body: NewTimetable, _: Teacher, t: TheTeams) -> Response:
    return await carry_out(
        t.add_timetable(class_id, [s.slot() for s in body.slots], body.school_year_end)
    )


class Break(BaseModel):
    first: date
    last: date

    @model_validator(mode="after")
    def ends_on_or_after_first(self) -> "Break":
        if self.last < self.first:
            raise ValueError("a break ends on or after its first day")
        return self


class SlotChange(BaseModel):
    old: WeeklySlot
    new: WeeklySlot
    from_date: date


@router.post("/api/classes/{class_id}/breaks", status_code=204)
async def cancel_break(class_id: str, body: Break, _: Teacher, t: TheTeams) -> Response:
    from_today(body.first)
    return await carry_out(t.cancel_lessons(class_id, body.first, body.last))


@router.post("/api/classes/{class_id}/timetable/change", status_code=204)
async def change_slot(class_id: str, body: SlotChange, _: Teacher, t: TheTeams) -> Response:
    from_today(body.from_date)
    return await carry_out(
        t.change_slot(class_id, body.old.slot(), body.new.slot(), body.from_date)
    )
