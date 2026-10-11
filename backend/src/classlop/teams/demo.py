"""Invented Classes for the demo school, written by `write_demo_teams` for the demo-school script.
They go straight into the `teams` tables, as the area keeps them: Lessons as the calendar sync
leaves them, Attendance as a fetch leaves it, no Teams tenant needed."""

import random
import unicodedata
import uuid
from datetime import datetime, time, timedelta

from sqlalchemy import delete
from ulid import ULID

from classlop import items
from classlop.shared.db import sessions
from classlop.shared.models import Schedule
from classlop.teams.assignment_records import AssignmentRecord, SubmissionRecord
from classlop.teams.ids import as_uuid
from classlop.teams.models import (
    AttendeeRecord,
    CalendarEventRecord,
    CalendarSeriesRecord,
    ClassRecord,
    FetchRecord,
    LessonRecord,
    OverrideRecord,
    StudentRecord,
)
from classlop.teams.service import WARSAW
from classlop.teams.types import LESSON, Assignment, Student, Submission, SubmissionState

CLASSES = ("1A", "2B", "3C")
STUDENTS_PER_CLASS = 25
ITEMS_PER_ASSIGNMENT = 3
# (first name, is a girl)
FIRST_NAMES = [
    ("Ala", True), ("Bartek", False), ("Celina", True), ("Damian", False), ("Ewa", True),
    ("Filip", False), ("Gosia", True), ("Hubert", False), ("Iga", True), ("Jakub", False),
    ("Kasia", True), ("Leon", False), ("Maja", True), ("Norbert", False), ("Olga", True),
    ("Patryk", False), ("Roksana", True), ("Szymon", False), ("Tola", True), ("Urban", False),
    ("Wiktoria", True), ("Zenon", False), ("Agata", True), ("Borys", False), ("Dorota", True),
]  # fmt: skip
# (boy's form, girl's form); 31 is prime, so no two Students share both names.
SURNAMES = [
    ("Zielinski", "Zielinska"), ("Brzozowski", "Brzozowska"), ("Lipinski", "Lipinska"),
    ("Debski", "Debska"), ("Gorski", "Gorska"), ("Kaczmarski", "Kaczmarska"),
    ("Sowinski", "Sowinska"), ("Wrzosek", "Wrzosek"), ("Malinowski", "Malinowska"),
    ("Jaworski", "Jaworska"), ("Rybicki", "Rybicka"), ("Czerwinski", "Czerwinska"),
    ("Pawlak", "Pawlak"), ("Nowicki", "Nowicka"), ("Sadowski", "Sadowska"),
    ("Olszewski", "Olszewska"), ("Baran", "Baran"), ("Cieslak", "Cieslak"),
    ("Dudek", "Dudek"), ("Fijalkowski", "Fijalkowska"), ("Glinski", "Glinska"),
    ("Hoffmann", "Hoffmann"), ("Jankowski", "Jankowska"), ("Krajewski", "Krajewska"),
    ("Lewandowski", "Lewandowska"), ("Mroz", "Mroz"), ("Napiorkowski", "Napiorkowska"),
    ("Orlowski", "Orlowska"), ("Przybylski", "Przybylska"), ("Rutkowski", "Rutkowska"),
    ("Struzik", "Struzik"),
]  # fmt: skip
# Weekday (0 is Monday) and start hour of each Class's two weekly Lessons.
TIMETABLES = [((0, 8), (3, 9)), ((1, 10), (4, 8)), ((2, 11), (0, 12))]
LESSON_MINUTES = 45
TOPICS = [
    "Zbiory liczbowe i działania na nich",
    "Wzory skróconego mnożenia",
    "Równania liniowe z parametrem",
    "Układy równań",
    "Funkcja liniowa i jej wykres",
    "Nierówności kwadratowe",
    "Własności funkcji kwadratowej",
    "Ciągi liczbowe",
    "Procenty i punkty procentowe",
    "Trygonometria w trójkącie prostokątnym",
]
# Title, type, days from now to the due time (negative: past) and how many days a Student has.
ASSIGNMENTS = [
    ("Zbiory liczbowe", "homework", -24, 7),
    ("Wzory skróconego mnożenia", "quiz", -17, 1),
    ("Równania", "homework", -8, 7),
    ("Układy równań", "homework", 3, 7),
]
FORMER_DAYS_AGO = 20


def _slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L"))
    return "".join(c for c in plain if c.isalnum() or c == " ").lower().replace(" ", ".")


def student_names(index: int) -> str:
    """The name of the `index`th invented Student, unique among the first 775."""
    first, girl = FIRST_NAMES[index % len(FIRST_NAMES)]
    return f"{first} {SURNAMES[index * 7 % len(SURNAMES)][girl]}"


def _at(day: datetime, hour: int) -> datetime:
    return datetime.combine(day.astimezone(WARSAW).date(), time(hour, 0), WARSAW)


async def _clear() -> None:
    async with sessions().begin() as session:
        # Students, Lessons, Attendance and Assignments go with their Class.
        await session.execute(delete(ClassRecord))
        await session.execute(delete(CalendarSeriesRecord))
        for prefix in ("teams.give:", "teams.remind:", "teams.due:"):
            await session.execute(delete(Schedule).where(Schedule.name.like(f"{prefix}%")))


def _lessons(
    rng: random.Random, class_id: str, number: int, name: str, now: datetime, students: list
) -> list:
    """The Class's Lesson records from four weeks back to two ahead, with Attendance fetched for
    those that have ended."""
    records: list = []
    first = now - timedelta(days=28)
    for slot, (weekday, hour) in enumerate(TIMETABLES[number]):
        series = CalendarSeriesRecord(
            id=str(ULID()),
            subject=f"Matematyka {name}",
            state=LESSON,
            class_id=class_id,
            candidates=[],
        )
        records.append(series)
        for offset in range(43):
            day = first + timedelta(days=offset)
            if day.astimezone(WARSAW).weekday() != weekday:
                continue
            start = _at(day, hour)
            event_id = str(ULID())
            records.append(
                CalendarEventRecord(
                    id=event_id,
                    series_id=series.id,
                    starts_at=start,
                    ends_at=start + timedelta(minutes=LESSON_MINUTES),
                    cancelled=False,
                    join_url=f"https://teams.example/l/meetup-join/{event_id}",
                )
            )
            ended = start + timedelta(minutes=LESSON_MINUTES) < now
            if start < now + timedelta(days=7):
                topic = TOPICS[(len(records) + slot) % len(TOPICS)]
                records.append(
                    LessonRecord(id=event_id, class_id=class_id, topic=topic, single=False)
                )
            if ended:
                records.extend(_attendance(rng, class_id, event_id, start, students))
    return records


def _attendance(
    rng: random.Random, class_id: str, lesson_id: str, start: datetime, students: list
) -> list:
    records: list = [
        FetchRecord(
            lesson_id=lesson_id,
            class_id=class_id,
            start=start,
            fetched_at=start + timedelta(minutes=LESSON_MINUTES + 10),
        )
    ]
    for student in students:
        if student.former_since and student.former_since < start:
            continue
        roll = rng.random()
        if roll < 0.1:
            continue
        minutes = rng.randint(-3, 3) if roll < 0.85 else rng.randint(8, 15)
        records.append(
            AttendeeRecord(
                lesson_id=lesson_id,
                key=student.user_id,
                class_id=class_id,
                user_id=student.user_id,
                display_name=student.display_name,
                first_join=start + timedelta(minutes=minutes),
                seconds=(LESSON_MINUTES - max(minutes, 0) - rng.randint(0, 5)) * 60,
            )
        )
    if rng.random() < 0.15:
        guest = f"Gość {rng.randint(1, 99)}"
        records.append(
            AttendeeRecord(
                lesson_id=lesson_id,
                key=f"name:{guest}",
                class_id=class_id,
                user_id=None,
                display_name=guest,
                first_join=start + timedelta(minutes=2),
                seconds=30 * 60,
            )
        )
    return records


def _state(rng: random.Random, due_in_days: int) -> SubmissionState:
    roll = rng.random()
    if due_in_days > 0:
        return "handed_in" if roll < 0.2 else "graded" if roll < 0.4 else "not_handed_in"
    if roll < 0.07:
        return "missing"
    if roll < 0.11:
        return "excused"
    return "graded" if roll < 0.2 else "returned"


async def write_demo_teams(
    item_ids: list[uuid.UUID], now: datetime
) -> tuple[list[Assignment], list[Submission], list[Student]]:
    """About three Classes of 25 Students with Lessons, Attendance and Assignments whose Items are
    taken from `item_ids`; rewrites every Class, so nothing of an earlier run is left. Returns the
    Assignments, with their Items pinned, and their Submissions for `grading` to grade, and the
    Students."""
    await _clear()
    rng = random.Random(84)
    assignments: list[Assignment] = []
    submissions: list[Submission] = []
    everyone: list[Student] = []
    for number, name in enumerate(CLASSES):
        klass = ClassRecord(
            id=str(ULID()),
            team_id=str(uuid.uuid4()),
            general_channel_id=f"19:{uuid.uuid4().hex}@thread.tacv2",
            name=name,
            school_year_end=(now + timedelta(days=200)).date(),
            state="active",
        )
        students = []
        for n in range(STUDENTS_PER_CLASS):
            display = student_names(number * STUDENTS_PER_CLASS + n)
            user_id = str(uuid.uuid4())
            students.append(
                StudentRecord(
                    id=str(ULID()),
                    class_id=klass.id,
                    user_id=user_id,
                    display_name=display,
                    upn=f"{_slug(display)}@demo.classlop.example",
                    former_since=now - timedelta(days=FORMER_DAYS_AGO)
                    if n == STUDENTS_PER_CLASS - 1
                    else None,
                )
            )
        everyone.extend(Student.model_validate(s, from_attributes=True) for s in students)
        lessons = _lessons(rng, klass.id, number, name, now, students)
        fetched = next(r for r in lessons if isinstance(r, FetchRecord))
        # The Teacher's say outranks Teams: the first Student is Present at the first Lesson.
        lessons.append(
            OverrideRecord(
                lesson_id=fetched.lesson_id,
                student_id=students[0].id,
                class_id=klass.id,
                state="present",
            )
        )
        async with sessions().begin() as session:
            session.add(klass)
            await session.flush()
            session.add_all(students)
            await session.flush()
            # Parents first: the tables carry no relationships for the session to order by.
            for kinds in (
                (CalendarSeriesRecord,),
                (CalendarEventRecord, LessonRecord, FetchRecord),
                (AttendeeRecord, OverrideRecord),
            ):
                session.add_all(r for r in lessons if isinstance(r, kinds))
                await session.flush()
        for index, (title, kind, days, span) in enumerate(ASSIGNMENTS):
            due = _at(now + timedelta(days=days), 20)
            chosen = [
                item_ids[(number * len(ASSIGNMENTS) + index) * ITEMS_PER_ASSIGNMENT + k]
                for k in range(ITEMS_PER_ASSIGNMENT)
            ]
            given = due - timedelta(days=span)
            assignment_id = str(ULID())
            record = AssignmentRecord(
                id=assignment_id,
                class_id=klass.id,
                title=title,
                type=kind,
                state="closed" if days < 0 else "open",
                due_at=due,
                close_at=due + timedelta(days=2),
                reminder_on=True,
                whole_class=True,
                item_ids=chosen,
                item_versions=await items.give(
                    chosen, as_uuid(assignment_id), as_uuid(klass.id), given
                ),
                given_at=given,
            )
            rows = []
            for student in students:
                if student.former_since and given > student.former_since:
                    continue
                state = _state(rng, days)
                handed = None
                late = False
                if state in ("handed_in", "graded", "returned"):
                    late = rng.random() < 0.08
                    handed = (
                        due + timedelta(hours=3)
                        if late
                        else due - timedelta(hours=rng.randint(1, 60))
                    )
                rows.append(
                    SubmissionRecord(
                        id=str(ULID()),
                        assignment_id=record.id,
                        student_id=student.id,
                        state=state,
                        handed_in_at=handed,
                        late=late,
                        files=[],
                        excused_reason="Zwolnienie lekarskie" if state == "excused" else None,
                    )
                )
            async with sessions().begin() as session:
                session.add(record)
                await session.flush()
                session.add_all(rows)
            assignments.append(Assignment.model_validate(record, from_attributes=True))
            submissions.extend(Submission.model_validate(r, from_attributes=True) for r in rows)
    return assignments, submissions, everyone
