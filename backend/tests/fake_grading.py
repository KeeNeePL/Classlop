"""`grading` over the invented Classes, in memory, for the tests and the Playwright server, which
run without a database. It answers like `grading`: the same records and the same refusals, and the
Teacher's changes show in the results it reads back."""

import random
import uuid
from datetime import UTC, datetime

from classlop import grading
from classlop.dashboard import invented
from classlop.dashboard.reports import Assignment, ScoredItem, Submission


def _share(points: int, available: int) -> int:
    """Nothing, part or all of the Item's points: what WORK, FEEDBACK and MISTAKES are kept by."""
    return 2 if points == available else min(points, 1)


def _unsure(submission: Submission) -> int:
    """The Item a Held Submission's unsure reading is on: the second, or the only one."""
    return min(2, submission.items[-1].number)


def _drawn(submission: Submission) -> int:
    """The Item with a drawing that a Spot-check looks at: the last one."""
    return submission.items[-1].number


# Per Item number, by share: the Student's work and the AI's Feedback.
WORK = {
    1: ["$x = 5$", "$3x - 2x = 5 - 7$, więc $x = -2$", "$3x - 2x = 5 + 7$, więc $x = 12$"],
    2: [
        "$(a + 2 - a - 2)^2 = 0$",
        "$a^2 + 4a + 4 - a^2 - 4a + 4 = 8$",
        "$a^2 + 4a + 4 - (a^2 - 4a + 4) = 8a$",
    ],
    3: [
        "[rysunek nieczytelny]",
        "[rysunek: prosta przez $(0, 1)$] miejsce zerowe $x = 2$",
        "[rysunek: prosta przez $(0, -1)$ i $(1, 1)$] miejsce zerowe $x = \\frac{1}{2}$",
    ],
}
FEEDBACK = [
    "Brak poprawnego rozwiązania. Zacznij od przeniesienia niewiadomych na jedną stronę.",
    "Dobra metoda, ale błąd znaku przy przenoszeniu wyrazów na drugą stronę.",
    "Poprawnie.",
]
MISTAKES = ["brak metody", "błąd znaku"]
DESCRIPTIONS = [
    "Błąd znaku przy przenoszeniu wyrazów na drugą stronę",
    "Pominięte założenie, że mianownik jest różny od zera",
    "Błąd rachunkowy w ostatnim kroku",
]

Key = tuple[uuid.UUID, uuid.UUID]


class InMemoryGrader:
    """Grades the invented Submissions as `invented.scenario` has them."""

    def __init__(self) -> None:
        self.calls: list[list[uuid.UUID]] = []
        self.reset()

    def reset(self) -> None:
        self._overrides: dict[Key, int] = {}
        self._fixed: dict[Key, str] = {}
        self._feedback: dict[Key, str] = {}
        self._approved: dict[uuid.UUID, datetime] = {}
        self._graded_again: set[uuid.UUID] = set()

    @staticmethod
    def made_failed(submission: Submission) -> bool:
        """The invented data's failed grading: handed in with points, but not graded."""
        return submission.state == "handed_in" and bool(submission.items)

    def _failed(self, submission_id: uuid.UUID, submission: Submission) -> bool:
        return self.made_failed(submission) and submission_id not in self._graded_again

    @staticmethod
    def _find(submission_id: uuid.UUID) -> tuple[Assignment, Submission, datetime] | None:
        for a in invented.scenario(datetime.now(UTC)):
            for s in a.submissions:
                if invented.submission_id(a.id, s.student_id) == submission_id:
                    return a, s, invented.handed_in_at(a, s)
        return None

    def _hand_in(
        self, submission_id: uuid.UUID, handed_in_at: datetime
    ) -> tuple[Assignment, Submission]:
        """As in `grading`: a result is one hand-in's, and a newer hand-in replaces it."""
        found = self._find(submission_id)
        if found is None or not found[1].items or found[2] != handed_in_at:
            raise LookupError(f"no result for {submission_id} handed in at {handed_in_at}")
        return found[0], found[1]

    def _ai_points(self, key: Key, scored: ScoredItem) -> int:
        # A fixed Transcription pretends the AI misread correct work.
        return scored.available if key in self._fixed else scored.earned

    def _key(self, assignment: Assignment, submission: Submission, scored: ScoredItem) -> Key:
        return (
            invented.submission_id(assignment.id, submission.student_id),
            invented.item_id(assignment.id, scored.number),
        )

    async def result(
        self, submission_id: uuid.UUID, handed_in_at: datetime
    ) -> grading.Result | None:
        try:
            assignment, submission = self._hand_in(submission_id, handed_in_at)
        except LookupError:
            return None
        failed = self._failed(submission_id, submission)
        items = [] if failed else [self._item(assignment, submission, i) for i in submission.items]
        held = (
            [grading.Reason(reason="Niepewny odczyt", items=[_unsure(submission)])]
            if submission.held
            else []
        )
        drawn = (
            [grading.Reason(reason="Rysunek", items=[_drawn(submission)])]
            if submission.spot_check
            else []
        )
        return grading.Result(
            submission_id=submission_id,
            handed_in_at=handed_in_at,
            status="failed" if failed else "graded",
            held_reasons=held,
            spot_check_reasons=drawn,
            summary="",
            comment="",
            pdf_key=None,
            items=items,
            approved_at=self._approved.get(submission_id),
        )

    def _item(
        self, assignment: Assignment, submission: Submission, scored: ScoredItem
    ) -> grading.ItemResult:
        key = self._key(assignment, submission, scored)
        unsure = submission.held and scored.number == _unsure(submission)
        ai = self._ai_points(key, scored)
        share = _share(ai, scored.available)
        return grading.ItemResult.model_validate(
            {
                "item_id": key[1],
                "number": scored.number,
                "ai_points": ai,
                "max_points": scored.available,
                "reading": "unsure" if unsure else "readable",
                "drawing": submission.spot_check and scored.number == _drawn(submission),
                "doubt": False,
                "ai_transcription": WORK[scored.number][_share(scored.earned, scored.available)],
                "fixed_transcription": self._fixed.get(key),
                "feedback": FEEDBACK[share],
                "edited_feedback": self._feedback.get(key),
                "mistake": None if share == 2 else MISTAKES[share],
                "verification_note": "Druga lektura czyta $4a$ jako $4$." if unsure else None,
                "override": self._overrides.get(key),
                "effective_points": self._overrides.get(key, ai),
            }
        )

    def _changeable_item(
        self, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID
    ) -> ScoredItem:
        """In `grading`'s order: a failed result, an unknown Item, then the due time."""
        assignment, submission = self._hand_in(submission_id, handed_in_at)
        if self._failed(submission_id, submission):
            raise ValueError("a failed result has no Items to change; grade it again")
        scored = next(
            (i for i in submission.items if invented.item_id(assignment.id, i.number) == item_id),
            None,
        )
        if scored is None:
            raise LookupError(f"no Item {item_id} in this result")
        if datetime.now(UTC) < assignment.due:
            raise grading.TooEarly(f"changes open at the due time, {assignment.due.isoformat()}")
        return scored

    async def override(
        self, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, points: int
    ) -> None:
        scored = self._changeable_item(submission_id, handed_in_at, item_id)
        if not 0 <= points <= scored.available:
            raise ValueError(f"points must be 0 to {scored.available}")
        self._overrides[(submission_id, item_id)] = points

    async def fix_transcription(
        self,
        submission_id: uuid.UUID,
        handed_in_at: datetime,
        item_id: uuid.UUID,
        transcription: str,
    ) -> None:
        self._changeable_item(submission_id, handed_in_at, item_id)
        # As in `grading`: the Override and the Feedback edit judged the misreading, so both go.
        self._fixed[(submission_id, item_id)] = transcription
        self._overrides.pop((submission_id, item_id), None)
        self._feedback.pop((submission_id, item_id), None)

    async def edit_feedback(
        self, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, feedback: str
    ) -> None:
        # `grading` typesets the Feedback; unbalanced dollar signs are what fails it here.
        if feedback.count("$") % 2:
            raise ValueError("the Feedback will not typeset; check the $...$ maths")
        self._changeable_item(submission_id, handed_in_at, item_id)
        self._feedback[(submission_id, item_id)] = feedback

    async def approve(self, submission_id: uuid.UUID, handed_in_at: datetime) -> None:
        """As in `grading`, at any time: only the three changes wait for the due time."""
        _, submission = self._hand_in(submission_id, handed_in_at)
        if self._failed(submission_id, submission):
            raise ValueError("a failed result is graded again, not approved")
        self._approved[submission_id] = datetime.now(UTC)

    async def grade_again(self, submission_id: uuid.UUID, handed_in_at: datetime) -> None:
        """Finishes at once; `grading` enqueues a grading job instead."""
        _, submission = self._hand_in(submission_id, handed_in_at)
        if not self._failed(submission_id, submission):
            raise ValueError("only a failed result is graded again")
        self._graded_again.add(submission_id)

    async def results(self, assignment_ids: list[uuid.UUID]) -> list[grading.Result]:
        self.calls.append(assignment_ids)
        found = []
        for a in invented.scenario(datetime.now(UTC)):
            if invented.assignment_uuid(a.id) not in assignment_ids:
                continue
            for s in a.submissions:
                if s.items and (
                    r := await self.result(
                        invented.submission_id(a.id, s.student_id), invented.handed_in_at(a, s)
                    )
                ):
                    found.append(r)
        return found

    async def common_mistakes(self, assignment_id: uuid.UUID) -> list[grading.ItemMistakes]:
        """The first and last Items each have their mistakes, the middle one none."""
        assignment = next(
            (
                a
                for a in invented.scenario(datetime.now(UTC))
                if invented.assignment_uuid(a.id) == assignment_id
            ),
            None,
        )
        if assignment is None:
            return []
        rng = random.Random(assignment.id)
        ids = [invented.submission_id(assignment.id, s.student_id) for s in assignment.submissions]
        found = []
        numbers = sorted({i.number for i in (assignment.items[:1] + assignment.items[-1:])})
        for number, kinds in zip(numbers, (3, 1), strict=False):
            mistakes = [
                grading.Mistake(description=d, submission_ids=rng.sample(ids, (6, 4, 3)[k]))
                for k, d in enumerate(DESCRIPTIONS[:kinds])
            ]
            found.append(
                grading.ItemMistakes(
                    item_id=invented.item_id(assignment.id, number),
                    number=number,
                    mistakes=mistakes,
                )
            )
        return found
