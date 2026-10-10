"""The Class overview: Progress by Assignment type, the Assignments, the Class-average line,
Wymagają uwagi and the Student list."""

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel

from classlop.dashboard.reports.progress import Bar, SectionBar, counted, overall, progress
from classlop.dashboard.reports.records import (
    Assignment,
    AssignmentState,
    AssignmentType,
    ClassData,
    Student,
)
from classlop.items import CurriculumSection

# The order of the Progress columns.
TYPES: tuple[AssignmentType, ...] = ("quiz", "exam", "homework")
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


class TypeProgress(BaseModel):
    """Progress on one Assignment type; `average` is its points earned over available."""

    type: AssignmentType
    average: int | None
    sections: list[SectionBar]


class ClassOverview(BaseModel):
    id: str
    name: str
    progress: list[TypeProgress]
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


def reasons(student: Student, data: ClassData, result: Bar) -> list[str]:
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
    # On the real ratio: 29.6% rounds to 30% on screen but is still under the line.
    if result.available and 100 * result.earned < LOW_PERCENT * result.available:
        found.append(f"Wynik {result.percent}%")
    if absent >= ABSENT_AT:
        found.append(f"{absent} nieobecności w ostatnich {ABSENT_OF} lekcjach")
    return found


def type_progress(
    kind: AssignmentType, data: ClassData, sections: Sequence[CurriculumSection]
) -> TypeProgress:
    items = counted(s for a in data.assignments if a.type == kind for s in a.submissions)
    return TypeProgress(
        type=kind, average=overall(items).percent, sections=progress(items, sections)
    )


def class_overview(data: ClassData, sections: Sequence[CurriculumSection]) -> ClassOverview:
    submissions = [s for a in data.assignments for s in a.submissions]
    rows = [row(a) for a in given(data)]
    results = {
        s.id: overall(counted(x for x in submissions if x.student_id == s.id))
        for s in data.students
    }
    students = [
        StudentRow(id=s.id, name=s.name, former=s.former, percent=results[s.id].percent)
        for s in data.students
    ]
    flagged = [
        Attention(
            student_id=s.id,
            name=s.name,
            former=s.former,
            reasons=why,
            percent=results[s.id].percent,
        )
        for s in data.students
        if (why := reasons(s, data, results[s.id]))
    ]
    # Worst first: most reasons, then the lowest result.
    flagged.sort(key=lambda a: (-len(a.reasons), 101 if a.percent is None else a.percent, a.name))
    return ClassOverview(
        id=data.id,
        name=data.name,
        progress=[type_progress(kind, data, sections) for kind in TYPES],
        assignments=rows,
        average_line=[
            AveragePoint(id=r.id, title=r.title, due=r.due, percent=r.average) for r in rows
        ],
        attention=flagged[:TOP],
        students=students,
    )
