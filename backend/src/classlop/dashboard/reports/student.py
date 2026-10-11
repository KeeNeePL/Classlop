"""The Student report: one Student over a chosen period, by the due time of their Assignments."""

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel

from classlop.dashboard.reports.grades import THRESHOLDS, suggested_grade
from classlop.dashboard.reports.overview import TYPES, TypeProgress, recent_sections, type_progress
from classlop.dashboard.reports.progress import HANDED_IN, bar, counted, overall, scored
from classlop.dashboard.reports.records import (
    Assignment,
    AssignmentType,
    ClassData,
    Submission,
    SubmissionState,
)
from classlop.items import CurriculumSection


class ReportRow(BaseModel):
    id: str
    title: str
    type: AssignmentType
    due: datetime
    submission_state: SubmissionState
    late: bool
    held: bool
    earned: int | None
    available: int | None
    percent: int | None
    suggested_grade: int | None


class Attendance(BaseModel):
    lessons: int
    absent: int
    # Lessons the Student was not Absent from, None with no Lessons.
    percent: int | None


class SubmissionCounts(BaseModel):
    late: int
    missing: int
    excused: int


class Point(BaseModel):
    """One Given Assignment on the chart, at its due time. Missing and Excused leave a gap, never
    a 0; a Submission not yet graded or still Held has no point either."""

    assignment_id: str
    title: str
    type: AssignmentType
    due: datetime
    percent: int | None
    # Over the Assignment's recipients only.
    class_average: int | None


class StudentReport(BaseModel):
    student_id: str
    name: str
    former: bool
    start: datetime | None
    end: datetime | None
    result: int | None
    attendance: Attendance
    counts: SubmissionCounts
    progress: list[TypeProgress]
    recent_sections: list[str]
    # Oldest first.
    points: list[Point]
    # Newest first.
    assignments: list[ReportRow]


def student_report(
    data: ClassData,
    student_id: str,
    sections: Sequence[CurriculumSection],
    start: datetime | None,
    end: datetime | None,
    thresholds: Sequence[int] = THRESHOLDS,
) -> StudentReport:
    """No `start` or `end` means no limit on that side."""
    student = next(s for s in data.students if s.id == student_id)

    def within(at: datetime) -> bool:
        return (start is None or at >= start) and (end is None or at <= end)

    # The Student's Assignments, each with their Submission alone, for Progress.
    alone: list[Assignment] = []
    rows: list[ReportRow] = []
    points: list[Point] = []
    submissions: list[Submission] = []
    given = (a for a in data.assignments if a.state != "draft" and within(a.due))
    for a in sorted(given, key=lambda a: a.due, reverse=True):
        s = next((s for s in a.submissions if s.student_id == student_id), None)
        if s is None:
            continue
        submissions.append(s)
        alone.append(a.model_copy(update={"submissions": (s,)}))
        result = overall(s.items) if scored(s) else None
        points.append(
            Point(
                assignment_id=a.id,
                title=a.title,
                type=a.type,
                due=a.due,
                percent=result.percent if result else None,
                class_average=overall(counted(a.submissions)).percent,
            )
        )
        rows.append(
            ReportRow(
                id=a.id,
                title=a.title,
                type=a.type,
                due=a.due,
                submission_state=s.state,
                late=s.late,
                held=s.held,
                earned=result.earned if result else None,
                available=result.available if result else None,
                percent=result.percent if result else None,
                suggested_grade=(
                    suggested_grade(result.earned, result.available, thresholds) if result else None
                ),
            )
        )
    # Progress as in the Class overview, over the Student's own Submissions.
    own = data.model_copy(update={"assignments": tuple(alone)})
    lessons = [lesson for lesson in data.lessons if within(lesson.start)]
    absent = sum(student_id in lesson.absent for lesson in lessons)
    present = bar(len(lessons) - absent, len(lessons))
    return StudentReport(
        student_id=student.id,
        name=student.name,
        former=student.former,
        start=start,
        end=end,
        result=overall(counted(submissions)).percent,
        attendance=Attendance(lessons=len(lessons), absent=absent, percent=present.percent),
        counts=SubmissionCounts(
            late=sum(s.late and s.state in HANDED_IN for s in submissions),
            missing=sum(s.state == "missing" for s in submissions),
            excused=sum(s.state == "excused" for s in submissions),
        ),
        progress=[type_progress(kind, own, sections) for kind in TYPES],
        recent_sections=recent_sections(own, sections),
        points=points[::-1],
        assignments=rows,
    )
