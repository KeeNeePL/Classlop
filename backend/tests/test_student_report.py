"""The Student report in the Reports core, on small invented data: no database, no HTTP."""

from datetime import UTC, datetime, timedelta

from classlop.dashboard.reports import (
    Assignment,
    ClassData,
    Lesson,
    ScoredItem,
    Student,
    Submission,
    student_report,
)
from classlop.dashboard.reports.records import AssignmentType, SubmissionState
from classlop.items import curriculum

SECTIONS = curriculum()[:2]
TOPIC = SECTIONS[0].topics[0].id
START = datetime(2026, 9, 1, 12, tzinfo=UTC)
STUDENTS = (Student(id="s1", name="Ala K."), Student(id="s2", name="Bartek M."))


def sub(
    student: str, earned: int | None = None, state: SubmissionState = "graded", **flags: bool
) -> Submission:
    items = (
        ()
        if earned is None
        else (ScoredItem(number=1, topic_ids=(TOPIC,), earned=earned, available=10),)
    )
    return Submission(student_id=student, state=state, items=items, **flags)


def work(day: int, *subs: Submission, type: AssignmentType = "quiz") -> Assignment:
    due = START + timedelta(days=day)
    return Assignment(
        id=f"w{day}",
        title=f"Praca {day}",
        type=type,
        given_at=due - timedelta(days=7),
        due=due,
        close=due,
        state="closed",
        items=(),
        submissions=subs,
    )


def report(*assignments: Assignment, lessons=(), start=None, end=None, thresholds=None):
    data = ClassData(id="c", name="1A", students=STUDENTS, assignments=assignments, lessons=lessons)
    extra = {} if thresholds is None else {"thresholds": thresholds}
    return student_report(data, "s1", SECTIONS, start, end, **extra)


def test_each_assignment_has_the_students_points_and_suggested_grade_newest_first():
    view = report(work(1, sub("s1", 9)), work(8, sub("s1", 4)), work(15, sub("s1", 7, held=True)))

    assert [(r.title, r.percent, r.suggested_grade) for r in view.assignments] == [
        ("Praca 15", None, None),
        ("Praca 8", 40, 2),
        ("Praca 1", 90, 5),
    ]
    assert view.assignments[0].held
    assert (view.name, view.result) == ("Ala K.", 65)


def test_the_period_keeps_assignments_due_in_it_and_lessons_held_in_it():
    lessons = tuple(
        Lesson(
            id=f"l{n}", start=START + timedelta(days=n), absent=frozenset({"s1"} if n < 2 else ())
        )
        for n in range(5)
    )
    view = report(
        work(1, sub("s1", 9)),
        work(3, sub("s1", 5)),
        work(9, sub("s1", 1)),
        lessons=lessons,
        start=START + timedelta(days=1),
        end=START + timedelta(days=4),
    )

    assert [r.title for r in view.assignments] == ["Praca 3", "Praca 1"]
    assert view.result == 70
    # Lessons on days 1 to 4; Absent on day 1 only.
    assert (view.attendance.lessons, view.attendance.absent, view.attendance.percent) == (4, 1, 75)


def test_counts_name_late_submissions_missing_and_excused():
    view = report(
        work(1, sub("s1", 9, late=True)),
        work(2, sub("s1", state="missing")),
        work(3, sub("s1", state="excused")),
        work(4, sub("s1", state="missing")),
    )

    assert (view.counts.late, view.counts.missing, view.counts.excused) == (1, 2, 1)
    assert view.attendance.percent is None


def test_the_chart_has_a_point_per_given_assignment_with_gaps_and_the_class_average():
    view = report(
        work(1, sub("s1", 8), sub("s2", 4)),
        work(2, sub("s1", state="missing"), sub("s2", 6)),
        work(3, sub("s1", state="excused"), sub("s2", 2, held=True)),
        # Given to selected Students only, s1 not among them.
        work(4, sub("s2", 10)),
        work(5, sub("s1", 5), sub("s2", 7), type="exam"),
    )

    # Missing and Excused leave a gap; the Held Submission is out of the Class average too.
    assert [(p.title, p.type, p.percent, p.class_average) for p in view.points] == [
        ("Praca 1", "quiz", 80, 60),
        ("Praca 2", "quiz", None, 60),
        ("Praca 3", "quiz", None, None),
        ("Praca 5", "exam", 50, 60),
    ]


def test_progress_is_the_students_own_split_by_type_as_in_the_class_overview():
    view = report(
        work(1, sub("s1", 6), sub("s2", 0)),
        work(2, sub("s1", 2, held=True)),
        work(3, sub("s1", 9), type="exam"),
    )

    by_type = {p.type: p.average for p in view.progress}
    assert by_type == {"quiz": 60, "exam": 90, "homework": None}
    quiz = next(p for p in view.progress if p.type == "quiz")
    assert quiz.sections[0].topics[0].percent == 60
    assert view.recent_sections == [SECTIONS[0].id]


def test_the_teachers_thresholds_set_the_suggested_grade():
    assert report(work(1, sub("s1", 8))).assignments[0].suggested_grade == 4
    strict = report(work(1, sub("s1", 8)), thresholds=(40, 60, 85, 95, 100))
    assert strict.assignments[0].suggested_grade == 3
