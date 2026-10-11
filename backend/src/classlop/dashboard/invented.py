"""Hardcoded stand-ins for the areas' per-Class reads, until they land; every screen built on them
shows the "ZMYŚLONE" badge."""

import random
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from classlop import grading
from classlop.dashboard import home
from classlop.dashboard.bank import Bank
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
from classlop.items import Filters, Item, ItemVersion, curriculum

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
MAX_ITEMS = 3

# The Item versions each invented Assignment pinned, as `teams` keeps them once it gives one.
# GRADING grades against them too, as `grading` keeps what it graded.
_pinned: list[list[ItemVersion]] = [[] for _ in TITLES]


def class_name(class_id: str, now: datetime) -> str | None:
    """The name of one of the sidebar's invented Classes."""
    return {c.id: c.name for c in home.invented(now).classes}.get(class_id)


def _students(class_id: str) -> tuple[Student, ...]:
    return tuple(
        Student(id=f"{class_id}-{i}", name=n, former=i == len(NAMES) - 1)
        for i, n in enumerate(NAMES)
    )


def students(class_id: str, now: datetime) -> tuple[Student, ...] | None:
    """The Students of one of the sidebar's invented Classes, without asking the bank."""
    return None if class_name(class_id, now) is None else _students(class_id)


def _unique(items: list[Item]) -> list[Item]:
    return list({i.id: i for i in items}.values())


def reset() -> None:
    """Unpin, so the next screen pins from the bank again."""
    _pinned[:] = [[] for _ in TITLES]


async def _pin(bank: Bank) -> None:
    """Assignment n pins the bank's Items of Curriculum sections n and n + 1, two of section n
    first, then one of n + 1, then the rest. While the bank pins nothing, every screen asks it
    again."""
    if any(_pinned):
        return
    found = []
    for section in curriculum()[: len(TITLES) + 1]:
        page = await bank.search("", Filters(curriculum_sections=[section.id]), 1, MAX_ITEMS)
        found.append(sorted(page.items, key=lambda i: i.created_at))
    _pinned[:] = [
        [i.version for i in _unique(own[:2] + next_[:1] + own[2:] + next_[1:])[:MAX_ITEMS]]
        for own, next_ in zip(found, found[1:], strict=False)
    ]


class Read(NamedTuple):
    data: ClassData
    # Each Assignment's Item versions in Item order, by the Assignment's id.
    versions: dict[str, list[ItemVersion]]


async def read(class_id: str, now: datetime, bank: Bank) -> Read | None:
    """One invented Class with the Teacher's changes made through GRADING, its Items' versions read
    from the bank in one call."""
    if (name := class_name(class_id, now)) is None:
        return None
    await _pin(bank)
    try:
        found = await bank.versions([v.id for a in _pinned for v in a])
    except LookupError:
        # The bank lost a pinned version, as when the database is filled again: pin afresh.
        reset()
        await _pin(bank)
        found = await bank.versions([v.id for a in _pinned for v in a])
    each = iter(found)
    versions = [[next(each) for _ in a] for a in _pinned]
    data = _made(class_id, name, now, versions)
    assignments = tuple(
        a.model_copy(update={"submissions": tuple(GRADING.applied(a, s) for s in a.submissions)})
        for a in data.assignments
    )
    return Read(
        data.model_copy(update={"assignments": assignments}),
        {a.id: v for a, v in zip(assignments, versions, strict=True)},
    )


def handed_in_at(assignment: Assignment, submission: Submission) -> datetime:
    """When the Submission's current hand-in came in, which `teams` will know."""
    return assignment.due + (timedelta(hours=2) if submission.late else -timedelta(days=1))


def _made(
    class_id: str, name: str, now: datetime, versions: Sequence[Sequence[ItemVersion]]
) -> ClassData:
    """`versions` are each Assignment's Items; their tags and points are the Items'. In each Class,
    one Submission's grading failed. Times are on the hour, so a hand-in keeps its time from the
    page to the Teacher's change."""
    now = now.replace(minute=0, second=0, microsecond=0)
    rng = random.Random(class_id)
    # Its own sequence, so the flags never move the points.
    flags = random.Random(f"{class_id}-flags")
    # The first Student is weak, the second misses the last Assignments, the third skips Lessons.
    ability = [0.2, 0.6, 0.7, 0.9, 0.5, 0.8, 0.65, 0.75]
    students = _students(class_id)
    assignments = []
    for n, (title, pinned) in enumerate(zip(TITLES, versions, strict=True)):
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
                # As many draws whatever the Items, so the bank never moves the other figures.
                draws = [rng.uniform(-0.25, 0.25) for _ in range(MAX_ITEMS)]
                scored = tuple(
                    ScoredItem(
                        number=k,
                        topic_ids=tuple(t.id for t in v.curriculum_topics),
                        earned=round(v.points * max(0, min(1, a + d))),
                        available=v.points,
                    )
                    for k, (v, d) in enumerate(zip(pinned, draws, strict=False), 1)
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
                items=tuple(
                    AssignmentItem(number=k, points=v.points) for k, v in enumerate(pinned, 1)
                ),
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
        for a in _made(c.id, c.name, now, _pinned).assignments:
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
    numbers = sorted({i.number for i in (assignment.items[:1] + assignment.items[-1:])})
    for number, kinds in zip(numbers, (3, 1), strict=False):
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
