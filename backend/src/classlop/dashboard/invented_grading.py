"""The `grading` interface over the invented Classes, in memory, until #82 reads the real results.
It answers like `grading`: the same records, the same refusals, and the Teacher's changes show in
every Report built on the invented data."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from classlop import grading
from classlop.dashboard.reports import Assignment, ScoredItem, Submission

# Per Item number: the Item's text, then the Student's work and the AI's remark by points earned.
TEXTS = {
    1: "Rozwiąż równanie $3x - 7 = 2x + 5$.",
    2: "Uprość wyrażenie $(a + 2)^2 - (a - 2)^2$.",
    3: "Narysuj wykres funkcji $f(x) = 2x - 1$ i odczytaj jej miejsce zerowe.",
}
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
REMARKS = [
    "Brak poprawnego rozwiązania. Zacznij od przeniesienia niewiadomych na jedną stronę.",
    "Dobra metoda, ale błąd znaku przy przenoszeniu wyrazów na drugą stronę.",
    "Poprawnie.",
]
MISTAKES = ["brak metody", "błąd znaku"]


class InventedGrading:
    """`find` gives an invented Submission by its `grading` id, as the invented data first made
    it. Lookups go by Submission alone: the invented times move with the clock."""

    def __init__(self, find: Callable[[uuid.UUID], tuple[Assignment, Submission] | None]):
        self._find = find
        self.reset()

    def reset(self) -> None:
        self._overrides: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        self._fixed: dict[tuple[uuid.UUID, uuid.UUID], str] = {}
        self._feedback: dict[tuple[uuid.UUID, uuid.UUID], str] = {}
        self._approved: dict[uuid.UUID, datetime] = {}
        self._graded_again: set[uuid.UUID] = set()

    @staticmethod
    def submission_id(assignment_id: str, student_id: str) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"{assignment_id}/{student_id}")

    @staticmethod
    def item_id(assignment_id: str, number: int) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"{assignment_id}#{number}")

    @staticmethod
    def failed(submission: Submission) -> bool:
        """Handed in with points but not graded: the invented data's failed grading."""
        return submission.state == "handed_in" and bool(submission.items)

    async def result(
        self, submission_id: uuid.UUID, handed_in_at: datetime | None = None
    ) -> grading.Result | None:
        found = self._find(submission_id)
        if found is None or not found[1].items:
            return None
        assignment, submission = found
        failed = self.failed(submission) and submission_id not in self._graded_again
        approved_at = self._approved.get(submission_id)
        items = [] if failed else [self._item(assignment, submission, i) for i in submission.items]
        held = [grading.Reason(reason="Niepewny odczyt", items=[2])] if submission.held else []
        drawing = [grading.Reason(reason="Rysunek", items=[3])] if submission.spot_check else []
        return grading.Result(
            submission_id=submission_id,
            handed_in_at=assignment.due
            + (timedelta(hours=2) if submission.late else -timedelta(days=1)),
            status="failed" if failed else "graded",
            held_reasons=held,
            spot_check_reasons=drawing,
            summary="",
            comment="",
            pdf_key=None,
            items=items,
            approved_at=approved_at,
        )

    def _item(
        self, assignment: Assignment, submission: Submission, scored: ScoredItem
    ) -> grading.ItemResult:
        sid = self.submission_id(assignment.id, submission.student_id)
        iid = self.item_id(assignment.id, scored.number)
        key = (sid, iid)
        unsure = submission.held and scored.number == 2
        # A fixed reading pretends the AI misread correct work.
        ai = scored.available if key in self._fixed else scored.earned
        return grading.ItemResult.model_validate(
            {
                "item_id": iid,
                "number": scored.number,
                "ai_points": ai,
                "max_points": scored.available,
                "reading": "unsure" if unsure else "readable",
                "drawing": submission.spot_check and scored.number == 3,
                "doubt": False,
                "ai_transcription": WORK[scored.number][scored.earned],
                "fixed_transcription": self._fixed.get(key),
                "feedback": REMARKS[ai],
                "edited_feedback": self._feedback.get(key),
                "mistake": None if ai == scored.available else MISTAKES[ai],
                "verification_note": "Druga lektura czyta $4a$ jako $4$." if unsure else None,
                "override": self._overrides.get(key),
                "effective_points": self._overrides.get(key, ai),
            }
        )

    def applied(self, assignment: Assignment, submission: Submission) -> Submission:
        """The Submission as the Reports see it after the Teacher's changes."""
        sid = self.submission_id(assignment.id, submission.student_id)
        if not submission.items:
            return submission
        failed = self.failed(submission) and sid not in self._graded_again
        changed = {
            "state": submission.state if failed or not self.failed(submission) else "graded",
            "held": submission.held and sid not in self._approved,
            "spot_check": submission.spot_check and sid not in self._approved,
            "items": tuple(
                i.model_copy(update={"earned": self._points(assignment, submission, i)})
                for i in submission.items
            ),
        }
        return submission.model_copy(update=changed)

    def _points(self, assignment: Assignment, submission: Submission, scored: ScoredItem) -> int:
        key = (
            self.submission_id(assignment.id, submission.student_id),
            self.item_id(assignment.id, scored.number),
        )
        if key in self._overrides:
            return self._overrides[key]
        return scored.available if key in self._fixed else scored.earned

    def _changeable(
        self, submission_id: uuid.UUID, item_id: uuid.UUID | None = None
    ) -> tuple[Assignment, Submission]:
        found = self._find(submission_id)
        if found is None or not found[1].items:
            raise LookupError(f"no result for {submission_id}")
        assignment, submission = found
        if item_id is not None:
            if self.failed(submission) and submission_id not in self._graded_again:
                raise ValueError("a failed result has no Items to change; grade it again")
            if item_id not in {self.item_id(assignment.id, i.number) for i in submission.items}:
                raise LookupError(f"no Item {item_id} in this result")
        if datetime.now(UTC) < assignment.due:
            raise grading.TooEarly(f"changes open at the due time, {assignment.due.isoformat()}")
        return assignment, submission

    async def override(
        self, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, points: int
    ) -> None:
        assignment, submission = self._changeable(submission_id, item_id)
        (top,) = (
            i.available
            for i in submission.items
            if self.item_id(assignment.id, i.number) == item_id
        )
        if not 0 <= points <= top:
            raise ValueError(f"points must be 0 to {top}")
        self._overrides[(submission_id, item_id)] = points

    async def fix_transcription(
        self,
        submission_id: uuid.UUID,
        handed_in_at: datetime,
        item_id: uuid.UUID,
        transcription: str,
    ) -> None:
        self._changeable(submission_id, item_id)
        # As in `grading`: the Override and the Feedback edit judged the misreading, so both go.
        self._fixed[(submission_id, item_id)] = transcription
        self._overrides.pop((submission_id, item_id), None)
        self._feedback.pop((submission_id, item_id), None)

    async def edit_feedback(
        self, submission_id: uuid.UUID, handed_in_at: datetime, item_id: uuid.UUID, feedback: str
    ) -> None:
        self._changeable(submission_id, item_id)
        self._feedback[(submission_id, item_id)] = feedback

    async def approve(self, submission_id: uuid.UUID, handed_in_at: datetime) -> None:
        _, submission = self._changeable(submission_id)
        if self.failed(submission) and submission_id not in self._graded_again:
            raise ValueError("a failed result is graded again, not approved")
        self._approved[submission_id] = datetime.now(UTC)

    async def grade_again(self, submission_id: uuid.UUID, handed_in_at: datetime) -> None:
        found = self._find(submission_id)
        if found is None or not found[1].items:
            raise LookupError(f"no result for {submission_id}")
        if not self.failed(found[1]) or submission_id in self._graded_again:
            raise ValueError("only a failed result is graded again")
        self._graded_again.add(submission_id)
