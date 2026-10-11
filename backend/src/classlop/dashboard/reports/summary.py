"""The Assignment summary: each recipient's Submission, the state counts, how each Item went and
a histogram of the Students' percents."""

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel

from classlop.dashboard.reports.grades import THRESHOLDS, suggested_grade
from classlop.dashboard.reports.progress import counted, overall
from classlop.dashboard.reports.records import (
    Assignment,
    AssignmentState,
    AssignmentType,
    Mistake,
    Student,
    Submission,
    SubmissionState,
)

# Whose times and recipients can still change, as in `teams`.
LIVE = ("scheduled", "open")
GRADED = ("graded", "returned")
HANDED_IN = ("handed_in", *GRADED)
BINS = 10
# Common mistakes shown per Item; `grading` gives them most frequent first.
MISTAKES = 3


class SummaryRow(BaseModel):
    student_id: str
    name: str
    former: bool
    state: SubmissionState
    late: bool
    held: bool
    # For the Teacher's Spot-check: Held, or with a drawing.
    flagged: bool
    earned: int | None
    available: int | None
    percent: int | None
    grade: int | None


class Counts(BaseModel):
    handed_in: int
    total: int
    late: int
    missing: int
    excused: int
    held: int


class CommonMistake(BaseModel):
    description: str
    count: int


class ItemSummary(BaseModel):
    number: int
    points: int
    average: int | None
    mistakes: list[CommonMistake]


class Choice(BaseModel):
    id: str
    name: str


class AssignmentSummary(BaseModel):
    id: str
    title: str
    type: AssignmentType
    state: AssignmentState
    given_at: datetime
    due: datetime
    close: datetime
    points: int
    # From the due time on; before it, only the hand-ins are counted.
    figures: bool
    average: int | None
    counts: Counts
    rows: list[SummaryRow]
    items: list[ItemSummary]
    # The Suggested grade thresholds, to mark on the histogram.
    thresholds: list[int]
    # Students per 10-point bin of their percent, 0-9 up to 90-100.
    histogram: list[int]
    # "Usuń pracę" only while nothing is handed in; `teams` checks again on deleting.
    deletable: bool
    # "Zmień termin" and "Dodaj uczniów" only while Scheduled or Open.
    changeable: bool
    # The Class's Students without a Submission, for "Dodaj uczniów".
    addable: list[Choice]


def scored(s: Submission) -> bool:
    return s.state in GRADED and not s.held


def flagged(s: Submission) -> bool:
    return s.held or s.spot_check


def row(s: Submission, student: Student, figures: bool, thresholds: Sequence[int]) -> SummaryRow:
    result = overall(s.items) if figures and scored(s) else None
    return SummaryRow(
        student_id=s.student_id,
        name=student.name,
        former=student.former,
        state=s.state,
        late=s.late,
        held=s.held,
        flagged=flagged(s),
        earned=result.earned if result else None,
        available=result.available if result else None,
        percent=result.percent if result else None,
        grade=suggested_grade(result.earned, result.available, thresholds) if result else None,
    )


def histogram(submissions: Sequence[Submission]) -> list[int]:
    bins = [0] * BINS
    for s in submissions:
        result = overall(s.items)
        if scored(s) and result.available:
            bins[min(BINS - 1, BINS * result.earned // result.available)] += 1
    return bins


def assignment_summary(
    assignment: Assignment,
    students: Sequence[Student],
    mistakes: Sequence[Mistake],
    now: datetime,
    thresholds: Sequence[int] = THRESHOLDS,
) -> AssignmentSummary:
    names = {s.id: s for s in students}
    order = {s.id: n for n, s in enumerate(students)}
    # Flagged first; otherwise in the order of the Class's Students.
    submissions = sorted(
        assignment.submissions, key=lambda s: (not flagged(s), order[s.student_id])
    )
    figures = now >= assignment.due
    graded = counted(submissions) if figures else []
    items = [
        ItemSummary(
            number=i.number,
            points=i.points,
            average=overall(x for x in graded if x.number == i.number).percent,
            mistakes=[
                CommonMistake(description=m.description, count=m.count)
                for m in mistakes
                if figures and m.number == i.number
            ][:MISTAKES],
        )
        for i in assignment.items
    ]
    changeable = assignment.state in LIVE
    recipients = {s.student_id for s in submissions}
    return AssignmentSummary(
        id=assignment.id,
        title=assignment.title,
        type=assignment.type,
        state=assignment.state,
        given_at=assignment.given_at,
        due=assignment.due,
        close=assignment.close,
        points=sum(i.points for i in assignment.items),
        figures=figures,
        average=overall(graded).percent,
        counts=Counts(
            handed_in=sum(s.state in HANDED_IN for s in submissions),
            total=len(submissions),
            late=sum(s.late and s.state in HANDED_IN for s in submissions),
            missing=sum(s.state == "missing" for s in submissions),
            excused=sum(s.state == "excused" for s in submissions),
            held=sum(s.held and s.state in GRADED for s in submissions),
        ),
        rows=[row(s, names[s.student_id], figures, thresholds) for s in submissions],
        items=items,
        thresholds=list(thresholds),
        histogram=histogram(submissions) if figures else [0] * BINS,
        deletable=not any(s.state in HANDED_IN for s in submissions),
        changeable=changeable,
        addable=[
            Choice(id=s.id, name=s.name)
            for s in students
            if changeable and not s.former and s.id not in recipients
        ],
    )
