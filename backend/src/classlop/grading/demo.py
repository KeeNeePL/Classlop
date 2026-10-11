"""Invented grading results for the demo school, written by `write_demo_grades` for the demo-school
script, as the AI would have left them."""

import random
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import delete

from classlop import items, teams
from classlop.grading.common_mistakes import chosen_option_mistake
from classlop.grading.models import (
    CommonMistake,
    CommonMistakesRun,
    GradedItem,
    GradedSubmission,
)
from classlop.shared.db import sessions
from classlop.teams.ids import as_uuid

# The share of closed Items a Student answers right, by Student: mostly fair, a few weak.
SKILL = (0.45, 0.9)
WRONG_OPTIONS = ("A", "C", "D")
MIN_SUBMISSIONS = 2


async def _clear() -> None:
    async with sessions().begin() as session:
        await session.execute(delete(GradedSubmission))
        await session.execute(delete(CommonMistake))
        await session.execute(delete(CommonMistakesRun))


async def write_demo_grades(
    assignments: list[teams.Assignment], submissions: list[teams.Submission]
) -> int:
    """A result for each Submission of `submissions` that is Graded or Returned, from the closed
    Items of its Assignment: some Held for the Teacher to approve, a few flagged for a Spot-check,
    and the Common mistakes of each closed Assignment. Rewrites every result; returns how many."""
    await _clear()
    rng = random.Random(84)
    skill: dict[str, float] = {}
    by_assignment = {a.id: a for a in assignments}
    versions = {
        v.id: v for v in await items.get_versions([v for a in assignments for v in a.item_versions])
    }
    written = 0
    wrong: dict[str, dict[uuid.UUID, dict[str, list[uuid.UUID]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    async with sessions().begin() as session:
        for submission in submissions:
            if submission.state not in ("graded", "returned") or not submission.handed_in_at:
                continue
            assignment = by_assignment[submission.assignment_id]
            student_skill = skill.setdefault(submission.student_id, rng.uniform(*SKILL))
            submission_uuid = as_uuid(submission.id)
            held = submission.state == "graded"
            rows = []
            for position, (item_id, version_id) in enumerate(
                zip(assignment.item_ids, assignment.item_versions, strict=True)
            ):
                version = versions[version_id]
                right = rng.random() < student_skill
                chosen = version.correct_options[0] if right else rng.choice(WRONG_OPTIONS)
                unsure = held and position == 0
                rows.append(
                    GradedItem(
                        submission_id=submission_uuid,
                        handed_in_at=submission.handed_in_at,
                        item_id=item_id,
                        position=position,
                        number=position + 1,
                        max_points=version.points,
                        ai_points=version.points if right else 0,
                        reading="unsure" if unsure else "readable",
                        drawing=False,
                        doubt=False,
                        ai_transcription=chosen,
                        fixed_transcription=None,
                        feedback="Poprawnie." if right else "Odpowiedź niepoprawna.",
                        mistake=None if right else chosen_option_mistake(chosen),
                        curriculum_topics=[t.name for t in version.curriculum_topics],
                    )
                )
                if not right:
                    wrong[assignment.id][item_id][chosen].append(submission_uuid)
            points = sum(r.ai_points for r in rows)
            reasons = [{"reason": "niepewny odczyt", "items": [1]}] if held else []
            session.add(
                GradedSubmission(
                    submission_id=submission_uuid,
                    handed_in_at=submission.handed_in_at,
                    assignment_id=as_uuid(assignment.id),
                    due_at=assignment.due_at,
                    approved_at=None,
                    status="graded",
                    held_reasons=reasons,
                    spot_check_reasons=reasons,
                    summary="Praca w większości poprawna."
                    if points * 2 >= len(rows)
                    else "Warto powtórzyć materiał przed kolejną pracą.",
                    comment=f"Wynik: {points}/{sum(r.max_points for r in rows)}.",
                    pdf_key=None,
                    grade_job=None,
                    items=rows,
                )
            )
            written += 1
        await session.flush()
        for assignment_id, per_item in wrong.items():
            number = {i: n + 1 for n, i in enumerate(by_assignment[assignment_id].item_ids)}
            for item_id, per_option in per_item.items():
                ranked = sorted(per_option.items(), key=lambda kv: -len(kv[1]))
                kept = [kv for kv in ranked if len(kv[1]) >= MIN_SUBMISSIONS][:3]
                for rank, (option, ids) in enumerate(kept):
                    session.add(
                        CommonMistake(
                            assignment_id=as_uuid(assignment_id),
                            item_id=item_id,
                            rank=rank,
                            number=number[item_id],
                            description=f"Zaznaczona odpowiedź {option}.",
                            submission_ids=[str(i) for i in ids],
                        )
                    )
            session.add(
                CommonMistakesRun(
                    assignment_id=as_uuid(assignment_id),
                    requested_at=datetime.now(UTC),
                    computed_at=datetime.now(UTC),
                )
            )
    return written
