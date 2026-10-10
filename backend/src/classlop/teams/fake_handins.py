"""Hand-ins becoming Submissions in memory, for FakeTeams. It follows handins.py step by step;
what the files make of a Submission is decided by the shared rules in submissions.py."""

import asyncio
import mimetypes
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from classlop.shared import jobs, storage
from classlop.teams import submissions
from classlop.teams.fake_giving import Share
from classlop.teams.types import Assignment, Student, Submission


@dataclass
class File:
    """A file in a Student's folder, as OneDrive has it."""

    id: str
    content: bytes
    uploaded_at: datetime


@dataclass
class Hand:
    """What the poll has seen of one Submission's folder: files by id as (name, uploaded_at,
    copy in storage), and where the hand-in stands."""

    files: dict[str, list] = field(default_factory=dict)
    changed_at: datetime | None = None
    pending: bool = False
    signature: str | None = None
    locked: bool = False

    def touch(self, at: datetime) -> None:
        self.changed_at = max(filter(None, [self.changed_at, at]))
        self.pending = True


class FakeHandIns:
    _clock: Callable[[], datetime]
    _assignments: dict[str, Assignment]
    _submissions: dict[str, dict[str, Submission]]
    _shares: dict[str, list[Share]]

    if TYPE_CHECKING:

        def _require_sign_in(self) -> None: ...
        def _save(self, assignment_id: str, **fields) -> Assignment: ...
        def _update(self, submission: Submission, **fields) -> Submission: ...
        async def get_assignment(self, assignment_id: str) -> Assignment: ...
        async def list_students(self, class_id: str) -> list[Student]: ...

    def _init_handins(self) -> None:
        self._drive: dict[str, dict[str, File]] = {}  # by folder path, then file name
        self._hands: dict[str, Hand] = {}  # by Submission

    # What a test does as a Student, as FakeGraph's.
    def upload(self, user_id: str, name: str, content: bytes, folder: str | None = None) -> None:
        shares = [s for s in self._shares.get(user_id, []) if not s.file]
        share = [s for s in shares if folder in (None, s.path)][-1]
        if share.role != "write":
            raise PermissionError(f"{share.path} is read-only")
        files = self._drive.setdefault(share.path, {})
        files[name] = File(
            files[name].id if name in files else uuid.uuid4().hex, content, self._clock()
        )

    def delete_file(self, user_id: str, name: str, folder: str | None = None) -> None:
        shares = [s for s in self._shares.get(user_id, []) if not s.file]
        share = [s for s in shares if folder in (None, s.path)][-1]
        del self._drive[share.path][name]

    async def poll_handins(self) -> int:
        self._require_sign_in()
        self._read()
        changed = await self._settle()
        changed += await self.close_due_assignments()
        self._lock_folders()
        return changed

    async def close_due_assignments(self) -> int:
        self._require_sign_in()
        due = [
            a.id
            for a in self._assignments.values()
            if a.state == "open" and a.close_at <= self._clock()
        ]
        return sum([await self._close(assignment_id) for assignment_id in due])

    def _hand(self, submission: Submission) -> Hand:
        return self._hands.setdefault(submission.id, Hand())

    def _open(self) -> list[tuple[Assignment, Submission]]:
        """The Submissions that still take files: those with a folder, of an Open Assignment."""
        return [
            (a, s)
            for a in self._assignments.values()
            if a.state == "open"
            for s in self._submissions[a.id].values()
            if s.folder_id and s.state not in submissions.FROZEN
        ]

    def _read(self) -> None:
        now = self._clock()
        for assignment, submission in self._open():
            hand, listing = self._hand(submission), self._drive.get(submission.folder_id or "", {})
            present = {f.id: (name, f) for name, f in listing.items()}
            for file_id in set(hand.files) - set(present):
                del hand.files[file_id]
                hand.touch(now)
            for file_id, (name, file) in present.items():
                if file.uploaded_at > assignment.close_at:
                    continue
                if (seen := hand.files.get(file_id)) is None or seen[:2] != [
                    name,
                    file.uploaded_at,
                ]:
                    hand.files[file_id] = [name, file.uploaded_at, None]
                    hand.touch(file.uploaded_at)

    async def _settle(self, assignment_id: str | None = None, *, force: bool = False) -> int:
        changed = 0
        for assignment, submission in self._open():
            hand = self._hand(submission)
            if hand.pending and assignment_id in (None, assignment.id):
                changed += await self._settle_one(assignment, submission, force)
        return changed

    async def _settle_one(self, assignment: Assignment, submission: Submission, force: bool) -> int:
        hand = self._hand(submission)
        ordered = sorted(hand.files.items(), key=lambda f: (f[1][1], f[1][0]))
        settlement = submissions.settle(
            state=submission.state,
            changed_at=hand.changed_at,
            files=[(file_id, seen[1]) for file_id, seen in ordered],
            due_at=assignment.due_at,
            now=self._clock(),
            force=force,
        )
        if settlement is None:
            return 0
        keys: list[str] = []
        if settlement.signature != hand.signature and settlement.handed_in_at:
            if not assignment.item_versions:
                return 0
            for _, seen in ordered:
                if seen[2] is None:
                    seen[2] = submissions.file_key(submission.id, seen[1], seen[0])
                    content = self._drive[submission.folder_id or ""][seen[0]].content
                    kind = mimetypes.guess_type(seen[0])[0] or "application/octet-stream"
                    await asyncio.to_thread(storage.put, seen[2], content, kind)
                keys.append(seen[2])
            key, payload = submissions.grade_job(
                assignment, submission.id, settlement.handed_in_at, keys
            )
            await jobs.enqueue("grading.grade", payload, key=key)
        hand.pending = False
        if settlement.signature == hand.signature:
            return 0
        hand.signature = settlement.signature
        self._update(
            submission,
            state=settlement.state,
            handed_in_at=settlement.handed_in_at,
            late=settlement.late,
            files=keys,
        )
        return 1

    async def _close(self, assignment_id: str) -> int:
        changed = await self._settle(assignment_id, force=True)
        assignment = self._assignments[assignment_id]
        students = {s.id: s for s in await self.list_students(assignment.class_id)}
        for submission in list(self._submissions[assignment_id].values()):
            if submissions.becomes_missing(
                submission.state,
                bool(students[submission.student_id].former_since),
                bool(submission.notice_id),
            ):
                self._update(submission, state="missing")
                changed += 1
        self._save(assignment_id, state="closed")
        self._lock_folders()
        return changed

    def _lock_folders(self) -> None:
        for assignment in self._assignments.values():
            for submission in self._submissions[assignment.id].values():
                hand = self._hand(submission)
                over = assignment.state == "closed" or submission.state == "returned"
                if over and submission.permission_id and not hand.locked:
                    for shares in self._shares.values():
                        shares[:] = [
                            s._replace(role="read") if s.path == submission.folder_id else s
                            for s in shares
                        ]
                    hand.locked = True
