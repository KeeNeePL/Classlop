"""Hardcoded stand-ins for the areas' per-Class reads, until they land; every screen built on them
shows the "ZMYŚLONE" badge."""

import random
import uuid
from datetime import UTC, datetime, timedelta

from classlop import grading
from classlop.dashboard import home
from classlop.dashboard.invented_grading import InventedGrading
from classlop.dashboard.reports import (
    Assignment,
    AssignmentItem,
    ClassData,
    Lesson,
    ScoredItem,
    Student,
    Submission,
)
from classlop.dashboard.reports.records import AssignmentType
from classlop.items import curriculum

NAMES = [
    "Ala K.",
    "Bartek M.",
    "Celina P.",
    "Damian R.",
    "Ewa S.",
    "Filip T.",
    "Gosia W.",
    "Hubert Z.",
]
TYPES: list[AssignmentType] = ["homework", "quiz", "exam", "quiz", "homework"]
TITLES = ["Zbiory liczbowe", "Wzory skróconego mnożenia", "Równania", "Układy równań", "Funkcje"]
DESCRIPTIONS = [
    "Błąd znaku przy przenoszeniu wyrazów na drugą stronę",
    "Pominięte założenie, że mianownik jest różny od zera",
    "Błąd rachunkowy w ostatnim kroku",
]
POINTS = 2
ITEM_TEXTS = {
    1: "Rozwiąż równanie $3x - 7 = 2x + 5$.",
    2: "Uprość wyrażenie $(a + 2)^2 - (a - 2)^2$.",
    3: "Narysuj wykres funkcji $f(x) = 2x - 1$ i odczytaj jej miejsce zerowe.",
}


def class_name(class_id: str, now: datetime) -> str | None:
    """The name of one of the sidebar's invented Classes."""
    return {c.id: c.name for c in home.invented(now).classes}.get(class_id)


def class_data(class_id: str, name: str, now: datetime) -> ClassData:
    """With the Teacher's changes made through GRADING."""
    data = _made(class_id, name, now)
    assignments = tuple(
        a.model_copy(update={"submissions": tuple(GRADING.applied(a, s) for s in a.submissions)})
        for a in data.assignments
    )
    return data.model_copy(update={"assignments": assignments})


def item_text(number: int) -> str:
    """The text of the Item at `number` in any invented Assignment, until #83 reads `items`."""
    return ITEM_TEXTS[number]


def handed_in_at(assignment: Assignment, submission: Submission) -> datetime:
    """When the Submission's current hand-in came in, which `teams` will know."""
    return assignment.due + (timedelta(hours=2) if submission.late else -timedelta(days=1))


def _made(class_id: str, name: str, now: datetime) -> ClassData:
    """Assignment n covers Curriculum section n and touches section n + 1, so five sections are
    assessed (more than Progress shows folded) and the rest show "brak danych". In each Class,
    one Submission's grading failed. Times are on the hour, so a hand-in keeps its time from the
    page to the Teacher's change."""
    now = now.replace(minute=0, second=0, microsecond=0)
    rng = random.Random(class_id)
    # Its own sequence, so the flags never move the points.
    flags = random.Random(f"{class_id}-flags")
    sections = curriculum()
    # The first Student is weak, the second misses the last Assignments, the third skips Lessons.
    ability = [0.2, 0.6, 0.7, 0.9, 0.5, 0.8, 0.65, 0.75]
    students = tuple(
        Student(id=f"{class_id}-{i}", name=n, former=i == len(NAMES) - 1)
        for i, n in enumerate(NAMES)
    )
    assignments = []
    for n, title in enumerate(TITLES):
        own, next_ = sections[n].topics, sections[n + 1].topics
        tags = [(own[0].id,), (own[1].id, next_[0].id), (next_[1].id,)]
        open_ = n == len(TITLES) - 1
        due = now + timedelta(days=7 * (n - len(TITLES) + 1) + 1)
        submissions = []
        for s, a in zip(students, ability, strict=True):
            late = held = spot_check = False
            # AI grades each Submission as it comes in, so an open Assignment has results too.
            if open_ and rng.random() >= 0.6:
                state, scored = "not_handed_in", ()
            elif not open_ and s.id.endswith("-1") and n >= len(TITLES) - 3:
                state, scored = "missing", ()
            else:
                state = "graded"
                scored = tuple(
                    ScoredItem(
                        number=k,
                        topic_ids=t,
                        earned=round(POINTS * max(0, min(1, a + rng.uniform(-0.25, 0.25)))),
                        available=POINTS,
                    )
                    for k, t in enumerate(tags, 1)
                )
                late = not open_ and flags.random() < 0.15
                held = flags.random() < 0.12
                spot_check = held or flags.random() < 0.1
            if not open_ and s.id.endswith("-4") and n == 1:
                state, scored, late, held, spot_check = "excused", (), False, False, False
            if not open_ and s.id.endswith("-5") and n == 0:
                state, late, held, spot_check = "handed_in", False, False, False
            submissions.append(
                Submission(
                    student_id=s.id,
                    state=state,
                    late=late,
                    held=held,
                    spot_check=spot_check,
                    items=scored,
                )
            )
        assignments.append(
            Assignment(
                id=f"{class_id}-{n}",
                title=title,
                type=TYPES[n],
                given_at=due - timedelta(days=7),
                due=due,
                close=due + (timedelta(days=7) if TYPES[n] == "homework" else timedelta(minutes=5)),
                state="open" if open_ else "closed",
                items=tuple(AssignmentItem(number=k, points=POINTS) for k in range(1, 4)),
                submissions=tuple(submissions),
            )
        )
    lessons = tuple(
        Lesson(
            id=f"{class_id}-l{n}",
            start=now - timedelta(days=7 * (12 - n)),
            absent=frozenset({f"{class_id}-2"} if n % 3 == 0 else ()),
        )
        for n in range(12)
    )
    return ClassData(
        id=class_id,
        name=name,
        students=students,
        assignments=tuple(assignments),
        lessons=lessons,
    )


def _find(submission_id: uuid.UUID) -> tuple[Assignment, Submission, datetime] | None:
    now = datetime.now(UTC)
    for c in home.invented(now).classes:
        for a in _made(c.id, c.name, now).assignments:
            for s in a.submissions:
                if InventedGrading.submission_id(a.id, s.student_id) == submission_id:
                    return a, s, handed_in_at(a, s)
    return None


GRADING = InventedGrading(_find)


def common_mistakes(assignment: Assignment) -> list[grading.ItemMistakes]:
    """In the shape `grading.common_mistakes` returns: the first and last Items each have their
    mistakes, the middle one none."""
    rng = random.Random(assignment.id)
    ids = [GRADING.submission_id(assignment.id, s.student_id) for s in assignment.submissions]
    found = []
    for number, kinds in ((1, 3), (3, 1)):
        mistakes = [
            grading.Mistake(description=d, submission_ids=rng.sample(ids, (6, 4, 3)[k]))
            for k, d in enumerate(DESCRIPTIONS[:kinds])
        ]
        found.append(
            grading.ItemMistakes(
                item_id=GRADING.item_id(assignment.id, number),
                number=number,
                mistakes=mistakes,
            )
        )
    return found
