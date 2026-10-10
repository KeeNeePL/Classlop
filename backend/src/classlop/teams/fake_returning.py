"""Returning Feedback in memory, for FakeTeams. It follows returning.py step by step; when a
Submission is returned and the words are the shared ones in feedback.py."""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from classlop import grading
from classlop.shared import jobs, schedule, storage
from classlop.shared.jobs import SignInRequired
from classlop.teams import feedback, ids
from classlop.teams.fake_giving import Share
from classlop.teams.fake_handins import File
from classlop.teams.types import Assignment, Student, Submission


@dataclass
class Sent:
    """What has been done for one version of the Feedback PDF, as FeedbackRecord."""

    path: str | None = None
    shared: bool = False
    sent: bool = False


class FakeReturning:
    _clock: Callable[[], datetime]
    _assignments: dict[str, Assignment]
    _submissions: dict[str, dict[str, Submission]]
    _assignment_dirs: dict[str, str]
    _folders: set[str]
    _drive: dict[str, dict[str, File]]
    _shares: dict[str, list[Share]]
    _chat_log: dict[str, list[str]]
    _rejected: set[str]

    if TYPE_CHECKING:

        def _require_sign_in(self) -> None: ...
        def _folder(self, parent: str, name: str) -> str: ...
        def _update(self, submission: Submission, **fields) -> Submission: ...
        def _lock_folders(self) -> None: ...
        async def list_students(self, class_id: str) -> list[Student]: ...

    def _init_returning(self) -> None:
        self._sent: dict[str, dict[str, Sent]] = {}  # by Submission, then PDF key
        self._order: dict[str, list[str]] = {}  # by Submission: the PDF keys in the order sent
        self._chat_attached: dict[str, list[tuple[str, bytes]]] = {}  # by Student's user id

    def chat_files(self, user_id: str) -> list[tuple[str, bytes]]:
        return self._chat_attached.get(user_id, [])

    async def submission_graded(self, submission_id: str, handed_in_at: datetime) -> None:
        self._require_sign_in()
        await self._consider(self._find(submission_id), handed_in_at)

    async def return_graded(self, assignment_id: str) -> int:
        self._require_sign_in()
        assignment = self._assignments[assignment_id]
        key, payload = feedback.common_mistakes_job(assignment)
        await jobs.enqueue("grading.common_mistakes", payload, key=key)
        graded = sorted(
            (s for s in self._submissions[assignment_id].values() if s.state == "graded"),
            key=lambda s: s.id,
        )
        returned = failed = 0
        for submission in graded:
            try:
                returned += await self._consider(submission)
            except SignInRequired:
                raise
            except Exception:
                failed += 1
        if failed:
            raise RuntimeError(f"{failed} Submissions not returned")
        return returned

    async def _schedule_due(self, assignment_id: str) -> None:
        await schedule.at(
            feedback.schedule_name(assignment_id),
            feedback.due_at(self._assignments[assignment_id].due_at, self._clock()),
            "teams.assignment_due",
            {"assignment_id": assignment_id},
        )

    def _find(self, submission_id: str) -> Submission:
        for table in self._submissions.values():
            for submission in table.values():
                if submission.id == submission_id:
                    return submission
        raise LookupError(submission_id)

    async def _consider(self, submission: Submission, handed_in_at: datetime | None = None) -> int:
        if submission.handed_in_at is None or handed_in_at not in (None, submission.handed_in_at):
            return 0
        found = await grading.result(ids.as_uuid(submission.id), submission.handed_in_at)
        if found is None or found.status != "graded":
            return 0
        assignment = self._assignments[submission.assignment_id]
        order = self._order.get(submission.id, [])
        action = feedback.step(
            state=submission.state,
            late=submission.late,
            due_at=assignment.due_at,
            now=self._clock(),
            held=found.held,
            pdf_key=found.pdf_key or "",
            sent=order[-1] if order else None,
        )
        if action in ("mark", "return") and submission.state == "handed_in":
            submission = self._update(submission, state="graded")
        if action in ("return", "correct"):
            await self._send(submission, assignment, found, corrected=action == "correct")
            return 1
        return 0

    async def _send(
        self,
        submission: Submission,
        assignment: Assignment,
        found: grading.Result,
        *,
        corrected: bool,
    ) -> None:
        key = found.pdf_key or ""
        sent = self._sent.setdefault(submission.id, {}).setdefault(key, Sent())
        if sent.sent:
            return
        if not submission.chat_id:
            raise RuntimeError("the Student has no chat yet")
        student = next(
            s
            for s in await self.list_students(assignment.class_id)
            if s.id == submission.student_id
        )
        name = feedback.attachment_name(assignment)
        content = b""
        if key and sent.path is None:
            content = await asyncio.to_thread(storage.get, key)
            folder = self._feedback_folder(assignment.id)
            files = self._drive.setdefault(folder, {})
            file_name = _free(files, feedback.file_name(student.display_name))
            files[file_name] = File(uuid.uuid4().hex, content, self._clock())
            sent.path = f"{folder}/{file_name}"
        if key and not sent.shared:
            self._shares.setdefault(student.user_id, []).append(
                Share(
                    sent.path or "",
                    "read",
                    f"https://onedrive.example.org/{uuid.uuid4().hex}",
                    True,
                )
            )
            sent.shared = True
        if student.user_id in self._rejected:
            raise RuntimeError("the chat was refused")
        folder, _, file_name = (sent.path or "").rpartition("/")
        if key:
            content = self._drive[folder][file_name].content
            self._chat_attached.setdefault(student.user_id, []).append((name, content))
        self._chat_log.setdefault(student.user_id, []).append(
            feedback.message_html(
                assignment, found.comment, corrected, uuid.uuid4().hex if key else None
            )
        )
        sent.sent = True
        self._order.setdefault(submission.id, []).append(key)
        if not corrected:
            self._update(submission, state="returned")
            self._lock_folders()

    def _feedback_folder(self, assignment_id: str) -> str:
        parent = self._assignment_dirs[assignment_id]
        path = f"{parent}/{feedback.FOLDER}"
        return path if path in self._folders else self._folder(parent, feedback.FOLDER)


def _free(files: dict, name: str) -> str:
    """What OneDrive calls a new file whose name is taken, under conflictBehavior=rename."""
    stem, dot, ext = name.rpartition(".")
    candidate, n = name, 0
    while candidate in files:
        n += 1
        candidate = f"{stem} {n}{dot}{ext}"
    return candidate
