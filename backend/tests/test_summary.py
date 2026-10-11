"""The Assignment summary in the Reports core, on small invented data: no database, no HTTP."""

from datetime import UTC, datetime, timedelta

from classlop.dashboard.reports import (
    Assignment,
    AssignmentItem,
    Mistake,
    ScoredItem,
    Student,
    Submission,
    assignment_summary,
)
from classlop.dashboard.reports.records import AssignmentState, SubmissionState

DUE = datetime(2026, 9, 14, 20, tzinfo=UTC)
AFTER = DUE + timedelta(hours=1)
BEFORE = DUE - timedelta(hours=1)
STUDENTS = tuple(Student(id=f"s{n}", name=f"Uczeń {n}") for n in range(1, 6))
# Two Items, 4 and 6 points: a Submission's points are its two scores out of 10.
ITEMS = (AssignmentItem(number=1, points=4), AssignmentItem(number=2, points=6))


def sub(
    student: str,
    first: int | None = None,
    second: int | None = None,
    state: SubmissionState = "graded",
    **flags: bool,
) -> Submission:
    scored = (
        ()
        if first is None
        else (
            ScoredItem(number=1, topic_ids=(), earned=first, available=4),
            ScoredItem(number=2, topic_ids=(), earned=second or 0, available=6),
        )
    )
    return Submission(student_id=student, state=state, items=scored, **flags)


def work(*subs: Submission, state: AssignmentState = "open") -> Assignment:
    return Assignment(
        id="w1",
        title="Równania",
        type="quiz",
        given_at=DUE - timedelta(days=7),
        due=DUE,
        close=DUE + timedelta(minutes=5),
        state=state,
        items=ITEMS,
        submissions=subs,
    )


def summary(*subs: Submission, now=AFTER, mistakes=(), students=STUDENTS, **kw):
    return assignment_summary(work(*subs, **kw), students, mistakes, now)


def test_each_recipient_has_a_row_with_state_and_points():
    view = summary(sub("s1", 3, 4), sub("s2", state="missing"))

    assert [(r.name, r.state, r.earned, r.available, r.percent) for r in view.rows] == [
        ("Uczeń 1", "graded", 7, 10, 70),
        ("Uczeń 2", "missing", None, None, None),
    ]
    assert view.points == 10


def test_a_held_submission_waits_for_the_teacher_and_stays_out_of_the_figures():
    view = summary(sub("s1", 4, 6), sub("s2", 0, 0, held=True, spot_check=True))

    held = view.rows[0]
    assert (held.name, held.held, held.percent, held.grade) == ("Uczeń 2", True, None, None)
    assert view.average == 100
    assert view.counts.held == 1
    assert sum(view.histogram) == 1


def test_once_approved_a_held_submission_counts():
    view = summary(sub("s1", 4, 6), sub("s2", 0, 0))

    assert view.average == 50
    assert sum(view.histogram) == 2


def test_before_the_due_time_only_hand_ins_are_counted():
    mistakes = [Mistake(number=1, description="zły znak", count=3)]
    view = summary(
        sub("s1", 4, 6),
        sub("s2", state="handed_in"),
        sub("s3", state="not_handed_in"),
        now=BEFORE,
        mistakes=mistakes,
    )

    assert not view.figures
    assert (view.counts.handed_in, view.counts.total) == (2, 3)
    assert [r.percent for r in view.rows] == [None, None, None]
    assert view.average is None
    assert view.histogram == [0] * 10
    assert [(i.number, i.average, i.mistakes) for i in view.items] == [(1, None, []), (2, None, [])]


def test_from_the_due_time_the_figures_show():
    view = summary(sub("s1", 4, 6), now=DUE)

    assert view.figures
    assert view.rows[0].percent == 100


def test_each_item_has_its_average_and_at_most_three_common_mistakes_from_grading():
    mistakes = [Mistake(number=2, description=f"błąd {n}", count=5 - n) for n in range(1, 5)] + [
        Mistake(number=1, description="zły znak", count=3)
    ]
    view = summary(sub("s1", 4, 0), sub("s2", 2, 3), sub("s3", 0, 0, held=True), mistakes=mistakes)

    first, second = view.items
    # Item 1: 6 of 8 points; Item 2: 3 of 12. The Held Submission is left out.
    assert (first.number, first.points, first.average) == (1, 4, 75)
    assert (second.number, second.points, second.average) == (2, 6, 25)
    assert [(m.description, m.count) for m in first.mistakes] == [("zły znak", 3)]
    assert [m.description for m in second.mistakes] == ["błąd 1", "błąd 2", "błąd 3"]


def test_state_counts_name_late_missing_excused_and_held():
    view = summary(
        sub("s1", 4, 6, late=True),
        sub("s2", state="handed_in", late=True),
        sub("s3", state="missing"),
        sub("s4", state="excused"),
        sub("s5", 1, 1, held=True),
        state="closed",
    )

    c = view.counts
    assert (c.handed_in, c.total, c.late, c.missing, c.excused, c.held) == (3, 5, 2, 1, 1, 1)
    assert [r.late for r in view.rows if r.student_id in ("s1", "s2", "s3")] == [True, True, False]


def test_flagged_submissions_come_first_then_the_class_order():
    view = summary(
        sub("s4", 1, 1),
        sub("s3", 2, 2, spot_check=True),
        sub("s2", state="missing"),
        sub("s1", 3, 3, held=True, spot_check=True),
    )

    assert [(r.student_id, r.flagged) for r in view.rows] == [
        ("s1", True),
        ("s3", True),
        ("s2", False),
        ("s4", False),
    ]


def test_the_suggested_grade_follows_the_thresholds_on_the_real_ratio():
    subs = [sub(f"s{n}", *pts) for n, pts in enumerate([(0, 0), (3, 0), (4, 1), (4, 4)], 1)]
    view = summary(*subs, sub("s5", 4, 5))
    assert [r.grade for r in view.rows] == [1, 2, 3, 4, 5]
    assert view.thresholds == [30, 50, 70, 85, 100]

    strict = assignment_summary(
        work(sub("s1", 4, 6), sub("s2", 4, 5)),
        STUDENTS,
        [],
        AFTER,
        thresholds=(30, 50, 70, 95, 100),
    )
    assert [r.grade for r in strict.rows] == [6, 4]
    assert strict.thresholds == [30, 50, 70, 95, 100]


def test_the_histogram_bins_percents_by_ten_with_full_marks_in_the_top_bin():
    view = summary(sub("s1", 0, 0), sub("s2", 0, 1), sub("s3", 4, 5), sub("s4", 4, 6))

    # 0%, 10%, 90% and 100%.
    assert view.histogram == [1, 1, 0, 0, 0, 0, 0, 0, 0, 2]


def test_an_assignment_is_deletable_only_while_nothing_is_handed_in():
    assert summary(sub("s1", state="not_handed_in"), sub("s2", state="excused")).deletable
    assert not summary(sub("s1", state="not_handed_in"), sub("s2", state="handed_in")).deletable
    assert not summary(sub("s1", 1, 1)).deletable


def test_times_and_recipients_change_only_while_scheduled_or_open():
    students = (*STUDENTS[:3], Student(id="s9", name="Uczeń 9", former=True))
    view = summary(sub("s1", state="not_handed_in"), students=students)

    assert view.changeable
    # Students of the Class without a Submission yet; a Former student is not offered.
    assert [s.id for s in view.addable] == ["s2", "s3"]

    closed = summary(sub("s1", state="missing"), students=students, state="closed")
    assert not closed.changeable
    assert closed.addable == []
