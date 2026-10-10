"""The Class overview: Progress, the Assignments, the Class-average line, Wymagają uwagi and the
Student list."""

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel

from classlop.dashboard.reports.progress import SectionBar, counted, overall, progress
from classlop.dashboard.reports.records import (
    Assignment,
    AssignmentState,
    AssignmentType,
    ClassData,
    Student,
)
from classlop.items import CurriculumSection

HANDED_IN = ("handed_in", "graded", "returned")
# Wymagają uwagi: the fixed thresholds of #13.
MISSING_OF, MISSING_AT = 5, 2
LOW_PERCENT = 30
ABSENT_OF, ABSENT_AT = 10, 3
TOP = 5


class AssignmentRow(BaseModel):
    id: str
    title: str
    type: AssignmentType
    state: AssignmentState
    due: datetime
    average: int | None
    handed_in: int
    total: int


class AveragePoint(BaseModel):
    """One Given Assignment on the Class-average line, at its due time; no percent is a gap."""

    id: str
    title: str
    due: datetime
    percent: int | None


class StudentRow(BaseModel):
    id: str
    name: str
    former: bool
    percent: int | None


class Attention(BaseModel):
    student_id: str
    name: str
    former: bool
    reasons: list[str]
    percent: int | None


class ClassOverview(BaseModel):
    id: str
    name: str
    sections: list[SectionBar]
    assignments: list[AssignmentRow]
    average_line: list[AveragePoint]
    attention: list[Attention]
    students: list[StudentRow]


def given(data: ClassData) -> list[Assignment]:
    return sorted((a for a in data.assignments if a.state != "draft"), key=lambda a: a.due)


def row(a: Assignment) -> AssignmentRow:
    return AssignmentRow(
        id=a.id,
        title=a.title,
        type=a.type,
        state=a.state,
        due=a.due,
        average=overall(counted(a.submissions)).percent,
        handed_in=sum(s.state in HANDED_IN for s in a.submissions),
        total=len(a.submissions),
    )


def reasons(student: Student, data: ClassData, percent: int | None) -> list[str]:
    """The Missing window skips Excused Submissions and Assignments not yet closed, where nothing
    can be Missing."""
    window = [
        s
        for a in sorted(data.assignments, key=lambda a: a.due)
        if a.state == "closed"
        for s in a.submissions
        if s.student_id == student.id and s.state != "excused"
    ][-MISSING_OF:]
    missing = sum(s.state == "missing" for s in window)
    lessons = sorted(data.lessons, key=lambda lesson: lesson.start)[-ABSENT_OF:]
    absent = sum(student.id in lesson.absent for lesson in lessons)
    found = []
    if missing >= MISSING_AT:
        found.append(f"Nie oddano {missing} z ostatnich {MISSING_OF} prac")
    if percent is not None and percent < LOW_PERCENT:
        found.append(f"Wynik {percent}%")
    if absent >= ABSENT_AT:
        found.append(f"{absent} nieobecności w ostatnich {ABSENT_OF} lekcjach")
    return found


def class_overview(data: ClassData, sections: Sequence[CurriculumSection]) -> ClassOverview:
    submissions = [(a, s) for a in data.assignments for s in a.submissions]
    rows = [row(a) for a in given(data)]
    students = [
        StudentRow(
            id=s.id,
            name=s.name,
            former=s.former,
            percent=overall(counted(x for _, x in submissions if x.student_id == s.id)).percent,
        )
        for s in data.students
    ]
    flagged = [
        Attention(student_id=s.id, name=s.name, former=s.former, reasons=why, percent=r.percent)
        for s, r in zip(data.students, students, strict=True)
        if (why := reasons(s, data, r.percent))
    ]
    # Worst first: most reasons, then the lowest result.
    flagged.sort(key=lambda a: (-len(a.reasons), 101 if a.percent is None else a.percent, a.name))
    return ClassOverview(
        id=data.id,
        name=data.name,
        sections=progress(counted(s for _, s in submissions), sections),
        assignments=rows,
        average_line=[
            AveragePoint(id=r.id, title=r.title, due=r.due, percent=r.average) for r in rows
        ],
        attention=flagged[:TOP],
        students=students,
    )
