"""The Reports core on small invented data: no database, no clock, no HTTP."""

from datetime import UTC, datetime, timedelta

from classlop.dashboard.reports import (
    Assignment,
    ClassData,
    Lesson,
    ScoredItem,
    Student,
    Submission,
    class_overview,
)
from classlop.dashboard.reports.records import AssignmentState, AssignmentType, SubmissionState
from classlop.items import curriculum

SECTIONS = curriculum()[:3]
A1, A2 = SECTIONS[0].topics[0].id, SECTIONS[0].topics[1].id
B1 = SECTIONS[1].topics[0].id
START = datetime(2026, 9, 1, 12, tzinfo=UTC)


def item(earned: int, available: int, *topics: str) -> ScoredItem:
    return ScoredItem(topic_ids=topics, earned=earned, available=available)


def sub(
    student: str, *items: ScoredItem, state: SubmissionState = "graded", held: bool = False
) -> Submission:
    return Submission(student_id=student, state=state, held=held, items=items)


def work(
    n: int,
    *subs: Submission,
    state: AssignmentState = "closed",
    type: AssignmentType = "homework",
) -> Assignment:
    return Assignment(
        id=f"w{n}",
        title=f"Praca {n}",
        type=type,
        given_at=START + timedelta(days=n),
        due=START + timedelta(days=n + 7),
        state=state,
        submissions=subs,
    )


def overview(*assignments: Assignment, students=("s1",), lessons=()):
    data = ClassData(
        id="c",
        name="1A",
        students=tuple(Student(id=s, name=f"Uczeń {s}") for s in students),
        assignments=assignments,
        lessons=lessons,
    )
    return class_overview(data, SECTIONS)


def category(view, type: AssignmentType = "homework"):
    return next(p for p in view.progress if p.type == type)


def topic(view, topic_id: str, type: AssignmentType = "homework"):
    return next(t for s in category(view, type).sections for t in s.topics if t.id == topic_id)


def section(view, section_id: str, type: AssignmentType = "homework"):
    return next(s for s in category(view, type).sections if s.id == section_id)


def test_progress_is_points_earned_over_available_per_topic_and_section():
    view = overview(work(1, sub("s1", item(1, 2, A1), item(3, 3, A2))))

    assert (topic(view, A1).earned, topic(view, A1).available, topic(view, A1).percent) == (
        1,
        2,
        50,
    )
    assert topic(view, A2).percent == 100
    assert (section(view, SECTIONS[0].id).earned, section(view, SECTIONS[0].id).available) == (4, 5)
    assert section(view, SECTIONS[0].id).percent == 80


def test_a_multi_tag_item_counts_in_full_per_topic_and_once_per_section():
    view = overview(work(1, sub("s1", item(1, 2, A1, A2, B1))))

    assert (topic(view, A1).earned, topic(view, A1).available) == (1, 2)
    assert (topic(view, A2).earned, topic(view, A2).available) == (1, 2)
    assert (section(view, SECTIONS[0].id).earned, section(view, SECTIONS[0].id).available) == (1, 2)
    assert (section(view, SECTIONS[1].id).earned, section(view, SECTIONS[1].id).available) == (1, 2)


def test_missing_excused_held_and_ungraded_submissions_are_left_out():
    view = overview(
        work(
            1,
            sub("s1", item(1, 2, A1)),
            sub("s2", item(0, 9, A1), state="missing"),
            sub("s3", item(0, 9, A1), state="excused"),
            sub("s4", item(0, 9, A1), held=True),
            sub("s5", item(0, 9, A1), state="handed_in"),
            sub("s6", item(0, 9, A1), state="not_handed_in"),
            sub("s7", item(2, 2, A1), state="returned"),
        ),
        students=("s1", "s2", "s3", "s4", "s5", "s6", "s7"),
    )

    assert (topic(view, A1).earned, topic(view, A1).available) == (3, 4)


def test_what_was_never_assessed_has_no_percent_not_zero():
    view = overview(work(1, sub("s1", item(0, 2, A1))))

    assert topic(view, A1).percent == 0
    assert topic(view, A2).percent is None
    assert section(view, SECTIONS[1].id).percent is None
    assert section(view, SECTIONS[1].id).available == 0


def test_percent_rounds_half_up():
    view = overview(work(1, sub("s1", item(5, 8, A1))))

    assert topic(view, A1).percent == 63


def test_assignments_show_state_average_and_hand_ins_and_leave_drafts_out():
    view = overview(
        work(
            1,
            sub("s1", item(1, 2, A1)),
            sub("s2", item(2, 2, A1), state="returned"),
            sub("s3", item(0, 2, A1), state="missing"),
            sub("s4", state="handed_in"),
        ),
        work(2, state="draft"),
        work(3, state="scheduled", type="exam"),
        students=("s1", "s2", "s3", "s4"),
    )

    second, first = view.assignments
    assert (first.title, first.type, first.state) == ("Praca 1", "homework", "closed")
    assert (first.average, first.handed_in, first.total) == (75, 3, 4)
    assert (second.type, second.state, second.average, second.total) == (
        "exam",
        "scheduled",
        None,
        0,
    )


def test_assignments_come_newest_given_first_with_the_day_they_were_given():
    view = overview(work(2), work(3), work(1), work(4, state="draft"))

    assert [(a.title, a.given_at.day) for a in view.assignments] == [
        ("Praca 3", START.day + 3),
        ("Praca 2", START.day + 2),
        ("Praca 1", START.day + 1),
    ]


def test_the_student_list_has_former_students_labelled_and_counted_like_any():
    data = ClassData(
        id="c",
        name="1A",
        students=(Student(id="s1", name="Ala"), Student(id="s2", name="Bartek", former=True)),
        assignments=(work(1, sub("s1", item(1, 2, A1)), sub("s2", item(2, 2, A1))),),
    )

    view = class_overview(data, SECTIONS)

    assert [(s.name, s.former, s.percent) for s in view.students] == [
        ("Ala", False, 50),
        ("Bartek", True, 100),
    ]
    assert section(view, SECTIONS[0].id).percent == 75


def lesson(n: int, *absent: str) -> Lesson:
    return Lesson(id=f"l{n}", start=START + timedelta(days=n), absent=frozenset(absent))


def attention(view) -> list[tuple[str, list[str]]]:
    return [(a.student_id, a.reasons) for a in view.attention]


def test_two_missing_of_the_last_five_assignments_need_attention():
    ok = item(2, 2, A1)
    view = overview(
        work(1, sub("s1", state="missing"), sub("s2", ok), sub("s3", ok)),
        work(2, sub("s1", ok), sub("s2", state="missing"), sub("s3", ok)),
        work(3, sub("s1", state="missing"), sub("s2", ok), sub("s3", state="excused")),
        students=("s1", "s2", "s3"),
    )

    assert attention(view) == [("s1", ["Nie oddano 2 z ostatnich 5 prac"])]


def test_only_the_last_five_closed_assignments_count_and_excused_ones_are_skipped():
    ok = item(2, 2, A1)
    view = overview(
        work(1, sub("s1", state="missing")),
        work(2, sub("s1", state="missing")),
        work(3, sub("s1", ok)),
        work(4, sub("s1", state="excused")),
        work(5, sub("s1", ok)),
        work(6, sub("s1", ok)),
        work(7, sub("s1", ok)),
        work(8, sub("s1", state="not_handed_in"), state="open"),
    )

    assert view.attention == []


def test_a_result_under_thirty_percent_needs_attention():
    view = overview(
        work(1, sub("s1", item(29, 100, A1)), sub("s2", item(30, 100, A1)), sub("s3")),
        students=("s1", "s2", "s3"),
    )

    assert attention(view) == [("s1", ["Wynik 29%"])]


def test_three_absences_of_the_last_ten_lessons_need_attention():
    lessons = (
        lesson(1, "s1"),
        lesson(2, "s1", "s2"),
        lesson(3),
        lesson(4),
        lesson(5, "s1"),
        *(lesson(n) for n in range(6, 11)),
        lesson(11, "s1", "s2"),
        lesson(12, "s1"),
    )

    assert attention(overview(students=("s1", "s2"), lessons=lessons)) == [
        ("s1", ["3 nieobecności w ostatnich 10 lekcjach"])
    ]


def test_wymagaja_uwagi_is_the_five_worst_students_with_every_reason_and_former_ones_count():
    data = ClassData(
        id="c",
        name="1A",
        students=tuple(Student(id=f"s{n}", name=f"Uczeń {n}", former=n == 7) for n in range(1, 8)),
        assignments=(
            work(1, *(sub(f"s{n}", item(n - 1, 100, A1)) for n in range(1, 8))),
            work(2, sub("s7", state="missing")),
            work(3, sub("s7", state="missing")),
        ),
    )

    view = class_overview(data, SECTIONS)

    assert [(a.student_id, a.name, a.former, len(a.reasons)) for a in view.attention] == [
        ("s7", "Uczeń 7", True, 2),
        ("s1", "Uczeń 1", False, 1),
        ("s2", "Uczeń 2", False, 1),
        ("s3", "Uczeń 3", False, 1),
        ("s4", "Uczeń 4", False, 1),
    ]


def test_the_thirty_percent_line_is_judged_on_the_real_ratio_not_the_rounded_one():
    view = overview(
        work(1, sub("s1", item(296, 1000, A1)), sub("s2", item(300, 1000, A1))),
        students=("s1", "s2"),
    )

    assert attention(view) == [("s1", ["Wynik 30%"])]


def test_progress_is_split_into_quizzes_exams_and_homework_each_with_its_average():
    view = overview(
        work(1, sub("s1", item(1, 2, A1)), type="quiz"),
        work(2, sub("s1", item(3, 4, A1), item(1, 4, B1)), type="exam"),
        work(3, sub("s1", item(2, 2, A1)), type="homework"),
        work(4, sub("s1", item(0, 2, A1)), type="homework"),
    )

    assert [(c.type, c.average) for c in view.progress] == [
        ("quiz", 50),
        ("exam", 50),
        ("homework", 50),
    ]
    assert topic(view, A1, "quiz").percent == 50
    assert topic(view, A1, "exam").percent == 75
    assert topic(view, B1, "exam").percent == 25
    assert topic(view, A1, "homework").percent == 50
    assert section(view, SECTIONS[1].id, "quiz").percent is None


def test_a_category_without_graded_work_has_no_average_not_zero():
    view = overview(work(1, sub("s1", item(2, 2, A1))))

    assert [(c.type, c.average) for c in view.progress] == [
        ("quiz", None),
        ("exam", None),
        ("homework", 100),
    ]


def test_a_students_result_pools_every_category():
    view = overview(
        work(1, sub("s1", item(1, 2, A1)), type="quiz"),
        work(2, sub("s1", item(3, 6, A1)), type="exam"),
        work(3, sub("s1", item(2, 2, A1)), type="homework"),
    )

    assert view.students[0].percent == 60


def test_recent_sections_are_the_assessed_ones_newest_given_first():
    C1 = SECTIONS[2].topics[0].id
    view = overview(
        work(1, sub("s1", item(1, 2, A1))),
        work(2, sub("s1", item(1, 2, C1))),
        work(3, sub("s1", item(1, 2, B1, A1))),
        work(4, sub("s1", item(1, 2, C1), state="missing")),
    )

    assert view.recent_sections == [SECTIONS[0].id, SECTIONS[1].id, SECTIONS[2].id]
