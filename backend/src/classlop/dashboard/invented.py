"""Hardcoded stand-ins for the areas' per-Class reads, until they land; every screen built on them
says what is still invented. `grading` is not among them: its results are read for real, and
`scenario` is only what the tests' stand-in grades the invented Submissions as."""

import random
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import NamedTuple

from classlop import grading
from classlop.dashboard import home
from classlop.dashboard.bank import Bank
from classlop.dashboard.grader import Grader
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
MAX_ITEMS = 3
# The Submissions that have work for `grading` to have graded.
WITH_WORK = ("handed_in", "graded", "returned")

# The Item versions each invented Assignment pinned, as `teams` keeps them once it gives one.
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
    # The current result of each Submission that has one, by its Assignment's and Student's ids.
    results: dict[tuple[str, str], grading.Result]
    # Each hand-in's copies in storage, by its Assignment's and Student's ids.
    files: dict[tuple[str, str], list[str]]


def assignment_uuid(assignment_id: str) -> uuid.UUID:
    """The id `grading` knows an invented Assignment by."""
    return uuid.uuid5(uuid.NAMESPACE_URL, assignment_id)


def submission_id(assignment_id: str, student_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{assignment_id}/{student_id}")


def item_id(assignment_id: str, number: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{assignment_id}#{number}")


async def read(class_id: str, now: datetime, bank: Bank, grader: Grader) -> Read | None:
    """One invented Class: its Items' versions read from the bank in one call, and its points, Held
    and Spot-check flags from `grading` in one call."""
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
    by_id = {a.id: v for a, v in zip(data.assignments, versions, strict=True)}
    results = {
        r.submission_id: r
        for r in await grader.results([assignment_uuid(a.id) for a in data.assignments])
    }
    current: dict[tuple[str, str], grading.Result] = {}
    assignments = []
    for a in data.assignments:
        submissions = []
        for s in a.submissions:
            result = results.get(submission_id(a.id, s.student_id))
            # A newer hand-in still being graded has no result yet: its older one does not count.
            if result is not None and result.handed_in_at == handed_in_at(a, s):
                current[a.id, s.student_id] = result
            submissions.append(with_result(s, current.get((a.id, s.student_id)), by_id[a.id]))
        assignments.append(a.model_copy(update={"submissions": tuple(submissions)}))
    return Read(data.model_copy(update={"assignments": tuple(assignments)}), by_id, current, {})


def with_result(
    submission: Submission, result: grading.Result | None, versions: list[ItemVersion]
) -> Submission:
    """The Submission with `grading`'s points and flags. Work with no graded result is still
    being graded, or its grading failed."""
    if submission.state not in WITH_WORK:
        return submission
    if result is None or result.status != "graded":
        return submission.model_copy(
            update={"state": "handed_in", "held": False, "spot_check": False, "items": ()}
        )
    return submission.model_copy(
        update={
            "state": "returned" if submission.state == "returned" else "graded",
            "held": result.held,
            "spot_check": result.held or result.spot_check,
            "items": tuple(
                ScoredItem(
                    number=i.number,
                    topic_ids=tuple(
                        t.id
                        for t in (
                            versions[i.number - 1].curriculum_topics
                            if i.number <= len(versions)
                            else ()
                        )
                    ),
                    earned=i.points,
                    available=i.max_points,
                )
                for i in result.items
            ),
        }
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


def scenario(now: datetime) -> list[Assignment]:
    """Every invented Assignment as the tests' stand-in for `grading` grades it: the points, Held
    and Spot-check flags and the failed grading are in the Submissions."""
    return [
        a for c in home.invented(now).classes for a in _made(c.id, c.name, now, _pinned).assignments
    ]
