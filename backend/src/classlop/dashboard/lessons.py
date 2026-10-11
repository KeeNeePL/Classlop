"""The Lekcje tab and the Lesson page: Lessons, their Lesson topic and Attendance with the
Teacher's overrides, the lateness threshold, and the Teams meetings the Teacher is asked to sort.
Every change goes through `teams`."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from classlop import teams
from classlop.dashboard.actions import carry_out, refusing
from classlop.dashboard.classes import Name, Teacher, TheTeams

router = APIRouter()


class LessonRow(BaseModel):
    id: str
    start: datetime
    end: datetime
    topic: str | None
    cancelled: bool
    # A flag, not a block: the Lesson has started and still has no Lesson topic.
    missing_topic: bool


class LessonList(BaseModel):
    class_name: str
    read_only: bool
    lessons: list[LessonRow]


class AttendanceRow(BaseModel):
    id: str
    name: str
    former: bool
    # None until the first fetch.
    state: teams.AttendanceState | None
    minutes: int
    overridden: bool


class Unmatched(BaseModel):
    key: str
    name: str
    minutes: int


class LessonPage(LessonRow):
    class_name: str
    read_only: bool
    join_url: str
    fetched_at: datetime | None
    students: list[AttendanceRow]
    unmatched: list[Unmatched]


class NewLesson(BaseModel):
    start: datetime
    end: datetime
    topic: Name


class Topic(BaseModel):
    topic: Name


class Override(BaseModel):
    """None takes the Teacher's state away, back to the one derived from Teams."""

    state: teams.AttendanceState | None


class Link(BaseModel):
    key: str
    student_id: str


class Lateness(BaseModel):
    minutes: Annotated[int, Field(ge=0, le=60)]


class Answer(BaseModel):
    answer: str


def row(lesson: teams.Lesson, now: datetime) -> LessonRow:
    return LessonRow(
        id=lesson.id,
        start=lesson.start,
        end=lesson.end,
        topic=lesson.topic,
        cancelled=lesson.cancelled,
        missing_topic=lesson.topic is None and not lesson.cancelled and lesson.start <= now,
    )


async def find(t: teams.Teams, class_id: str, lesson_id: str) -> teams.Lesson:
    lesson = next((x for x in await t.list_lessons(class_id) if x.id == lesson_id), None)
    if lesson is None:
        raise HTTPException(404)
    return lesson


@router.get("/api/classes/{class_id}/lessons")
async def lessons(class_id: str, _: Teacher, t: TheTeams) -> LessonList:
    """Opening the tab brings the Lessons in step with the Teacher's Teams calendar first."""
    now = datetime.now(UTC)
    with refusing():
        klass = await t.get_class(class_id)
        await t.sync_calendar()
        found = await t.list_lessons(class_id)
    return LessonList(
        class_name=klass.name,
        read_only=klass.state != "active",
        lessons=[row(x, now) for x in found],
    )


@router.post("/api/classes/{class_id}/lessons", status_code=204)
async def add_lesson(class_id: str, body: NewLesson, _: Teacher, t: TheTeams) -> Response:
    return await carry_out(t.add_lesson(class_id, body.start, body.end, body.topic))


@router.get("/api/classes/{class_id}/lessons/{lesson_id}")
async def lesson(class_id: str, lesson_id: str, _: Teacher, t: TheTeams) -> LessonPage:
    with refusing():
        klass = await t.get_class(class_id)
        found = await find(t, class_id, lesson_id)
        attendance = await t.get_attendance(class_id, lesson_id)
        students = {s.id: s for s in await t.list_students(class_id)}
    rows = [
        AttendanceRow(
            id=e.student_id,
            name=students[e.student_id].display_name,
            former=students[e.student_id].former_since is not None,
            state=e.state,
            minutes=e.minutes,
            overridden=e.overridden,
        )
        for e in attendance.entries
    ]
    return LessonPage(
        **row(found, datetime.now(UTC)).model_dump(),
        class_name=klass.name,
        read_only=klass.state != "active",
        join_url=found.join_url,
        fetched_at=attendance.fetched_at,
        students=sorted(rows, key=lambda r: r.name),
        unmatched=[
            Unmatched(key=u.key, name=u.display_name, minutes=u.minutes)
            for u in attendance.unmatched
        ],
    )


@router.put("/api/classes/{class_id}/lessons/{lesson_id}/topic", status_code=204)
async def set_topic(
    class_id: str, lesson_id: str, body: Topic, _: Teacher, t: TheTeams
) -> Response:
    return await carry_out(t.set_lesson_topic(class_id, lesson_id, body.topic))


@router.post("/api/classes/{class_id}/lessons/{lesson_id}/refresh", status_code=204)
async def refresh(class_id: str, lesson_id: str, _: Teacher, t: TheTeams) -> Response:
    return await carry_out(t.refresh_attendance(class_id, lesson_id))


@router.put("/api/classes/{class_id}/lessons/{lesson_id}/attendance/{student_id}", status_code=204)
async def override(
    class_id: str, lesson_id: str, student_id: str, body: Override, _: Teacher, t: TheTeams
) -> Response:
    return await carry_out(t.override_attendance(class_id, lesson_id, student_id, body.state))


@router.post("/api/classes/{class_id}/lessons/{lesson_id}/attendees", status_code=204)
async def link_attendee(
    class_id: str, lesson_id: str, body: Link, _: Teacher, t: TheTeams
) -> Response:
    return await carry_out(t.link_attendee(class_id, body.key, body.student_id))


@router.get("/api/settings/lateness")
async def lateness(_: Teacher, t: TheTeams) -> Lateness:
    with refusing():
        return Lateness(minutes=int((await t.lateness_threshold()).total_seconds() // 60))


@router.put("/api/settings/lateness", status_code=204)
async def set_lateness(body: Lateness, _: Teacher, t: TheTeams) -> Response:
    return await carry_out(t.set_lateness_threshold(timedelta(minutes=body.minutes)))


@router.post("/api/calendar-questions/{question_id}", status_code=204)
async def answer_question(question_id: str, body: Answer, _: Teacher, t: TheTeams) -> Response:
    return await carry_out(t.answer_calendar_question(question_id, body.answer))
