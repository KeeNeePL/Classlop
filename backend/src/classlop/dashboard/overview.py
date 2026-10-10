"""The Class overview screen: one endpoint returns the ready overview of one Class."""

import random
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from classlop.dashboard import auth, home
from classlop.dashboard.reports import (
    Assignment,
    ClassData,
    ClassOverview,
    Lesson,
    ScoredItem,
    Student,
    Submission,
    class_overview,
)
from classlop.dashboard.reports.records import AssignmentType
from classlop.items import curriculum

router = APIRouter()

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


class OverviewResponse(ClassOverview):
    invented: bool


def invented(class_id: str, name: str, now: datetime) -> ClassData:
    """Hardcoded stand-in until the areas' per-Class reads land. Assignment n covers Curriculum
    section n and touches section n + 1, so five sections are assessed (more than Progress shows
    folded) and the rest show "brak danych"."""
    rng = random.Random(class_id)
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
        items = [(own[0].id,), (own[1].id, next_[0].id), (next_[1].id,)]
        open_ = n == len(TITLES) - 1
        submissions = []
        for s, a in zip(students, ability, strict=True):
            # AI grades each Submission as it comes in, so an open Assignment has results too.
            if open_ and rng.random() >= 0.6:
                state, scored = "not_handed_in", ()
            elif not open_ and s.id.endswith("-1") and n >= len(TITLES) - 3:
                state, scored = "missing", ()
            else:
                state = "graded"
                scored = tuple(
                    ScoredItem(
                        topic_ids=t,
                        earned=round(2 * max(0, min(1, a + rng.uniform(-0.25, 0.25)))),
                        available=2,
                    )
                    for t in items
                )
            submissions.append(Submission(student_id=s.id, state=state, items=scored))
        due = now + timedelta(days=7 * (n - len(TITLES) + 1) + 1)
        assignments.append(
            Assignment(
                id=f"{class_id}-{n}",
                title=title,
                type=TYPES[n],
                given_at=due - timedelta(days=7),
                due=due,
                state="open" if open_ else "closed",
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


@router.get("/api/classes/{class_id}/overview")
async def overview(class_id: str, _: Annotated[auth.Me, Depends(auth.teacher)]) -> OverviewResponse:
    now = datetime.now(UTC)
    names = {c.id: c.name for c in home.invented(now).classes}
    if class_id not in names:
        raise HTTPException(404)
    view = class_overview(invented(class_id, names[class_id], now), curriculum())
    return OverviewResponse(**view.model_dump(), invented=True)
