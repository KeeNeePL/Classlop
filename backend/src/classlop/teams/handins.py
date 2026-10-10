"""Turning the files Students upload into Submissions, through the Teacher's OneDrive. GraphTeams
inherits it. The drive delta says what changed in the hand-in folders, `submissions.py` decides
what the files make of a Submission, and closing is driven by the same poll."""

import asyncio
import logging
import mimetypes
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import or_, select

from classlop.shared import jobs, storage
from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.teams import submissions
from classlop.teams.assignment_records import AssignmentRecord, SubmissionRecord
from classlop.teams.graph import GraphClient, GraphError
from classlop.teams.handin_records import HandinCursor, HandinFileRecord
from classlop.teams.models import StudentRecord
from classlop.teams.types import Assignment

log = logging.getLogger(__name__)

ROOT_DELTA = "/me/drive/root/delta"


def _when(row: dict) -> datetime:
    return datetime.fromisoformat(row.get("lastModifiedDateTime") or row["createdDateTime"])


class HandIns:
    _graph: GraphClient
    _clock: Callable[[], datetime]

    if TYPE_CHECKING:

        async def get_assignment(self, assignment_id: str) -> Assignment: ...

    async def poll_handins(self) -> int:
        await self._read_delta()
        changed = await self._settle()
        changed += await self.close_due_assignments()
        await self._lock_folders()
        return changed

    async def close_due_assignments(self) -> int:
        async with sessions()() as session:
            due = await session.scalars(
                select(AssignmentRecord.id).where(
                    AssignmentRecord.state == "open", AssignmentRecord.close_at <= self._clock()
                )
            )
            due = list(due)
        return sum([await self._close(assignment_id) for assignment_id in due])

    async def _read_delta(self) -> None:
        """Take in what changed in the hand-in folders of Open Assignments: a file added or
        changed is part of its Student's hand-in, a file deleted or moved out is not."""
        async with sessions()() as session:
            cursor = await session.get(HandinCursor, "me")
        rows, link = await self._graph.get_delta(cursor.delta_link if cursor else ROOT_DELTA)
        now = self._clock()
        async with sessions().begin() as session:
            open_ = await session.execute(
                select(SubmissionRecord, AssignmentRecord)
                .join(AssignmentRecord, AssignmentRecord.id == SubmissionRecord.assignment_id)
                .where(
                    AssignmentRecord.state == "open",
                    SubmissionRecord.folder_id.is_not(None),
                    SubmissionRecord.state.not_in(list(submissions.FROZEN)),
                )
            )
            by_folder = {s.folder_id: (s, a) for s, a in open_}
            by_id = {s.id: s for s, _ in by_folder.values()}
            for row in rows:
                parent = row.get("parentReference", {}).get("id")
                file = await session.get(HandinFileRecord, row["id"])
                if "deleted" in row or parent not in by_folder:
                    if file and file.submission_id in by_id:
                        await session.delete(file)
                        _touch(by_id[file.submission_id], now)
                    continue
                if "file" not in row:
                    continue
                submission, assignment = by_folder[parent]
                uploaded_at = _when(row)
                if uploaded_at > assignment.close_at:
                    continue
                if file is None:
                    file = HandinFileRecord(id=row["id"], submission_id=submission.id)
                    session.add(file)
                if file.uploaded_at != uploaded_at or file.name != row["name"]:
                    file.s3_key = None
                file.name, file.uploaded_at = row["name"], uploaded_at
                _touch(submission, uploaded_at)
            await session.merge(HandinCursor(id="me", delta_link=link))

    async def _settle(self, assignment_id: str | None = None, *, force: bool = False) -> int:
        """Settle the Submissions whose folder has been quiet (all of an Assignment's, if
        `force`). A failure for one leaves it to the next poll."""
        async with sessions()() as session:
            query = select(SubmissionRecord.id).where(SubmissionRecord.pending)
            if assignment_id:
                query = query.where(SubmissionRecord.assignment_id == assignment_id)
            pending = list(await session.scalars(query.order_by(SubmissionRecord.id)))
        changed = 0
        for submission_id in pending:
            try:
                changed += await self._settle_one(submission_id, force)
            except SignInRequired:
                raise
            except Exception:
                log.exception("hand-in of submission %s not settled", submission_id)
        return changed

    async def _settle_one(self, submission_id: str, force: bool) -> int:
        async with sessions()() as session:
            row = await session.get_one(SubmissionRecord, submission_id)
            assignment = await self.get_assignment(row.assignment_id)
            files = list(
                await session.scalars(
                    select(HandinFileRecord)
                    .where(HandinFileRecord.submission_id == submission_id)
                    .order_by(HandinFileRecord.uploaded_at, HandinFileRecord.name)
                )
            )
            settlement = submissions.settle(
                state=row.state,
                changed_at=row.changed_at,
                files=[(f.id, f.uploaded_at) for f in files],
                due_at=assignment.due_at,
                now=self._clock(),
                force=force,
            )
            settled = row.signature
        if settlement is None:
            return 0
        keys: list[str] = []
        if settlement.signature != settled and settlement.handed_in_at:
            if not assignment.item_versions:
                return 0  # not yet frozen; the next poll settles it
            keys = [await self._copy(submission_id, f) for f in files]
            key, payload = submissions.grade_job(
                assignment, submission_id, settlement.handed_in_at, keys
            )
            await jobs.enqueue("grading.grade", payload, key=key)
        async with sessions().begin() as session:
            row = await session.get_one(SubmissionRecord, submission_id)
            row.pending = False
            if settlement.signature == settled:
                return 0
            row.state, row.handed_in_at, row.late = (
                settlement.state,
                settlement.handed_in_at,
                settlement.late,
            )
            row.signature, row.files = settlement.signature, keys
        return 1

    async def _copy(self, submission_id: str, file: HandinFileRecord) -> str:
        """The file's copy in storage, made once however many hand-ins it is part of."""
        if file.s3_key is None:
            response = await self._graph.request(
                "GET", f"/me/drive/items/{file.id}/content", follow_redirects=True
            )
            key = submissions.file_key(submission_id, file.uploaded_at, file.name)
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            await asyncio.to_thread(storage.put, key, response.content, kind)
            async with sessions().begin() as session:
                (await session.get_one(HandinFileRecord, file.id)).s3_key = key
            file.s3_key = key
        return file.s3_key

    async def _close(self, assignment_id: str) -> int:
        """Settle what is waiting, mark the Students who have not handed in Missing and close
        the Assignment; the folders turn read-only right after."""
        changed = await self._settle(assignment_id, force=True)
        async with sessions().begin() as session:
            waiting = await session.execute(
                select(SubmissionRecord, StudentRecord)
                .join(StudentRecord, StudentRecord.id == SubmissionRecord.student_id)
                .where(SubmissionRecord.assignment_id == assignment_id)
            )
            for submission, student in waiting:
                if submissions.becomes_missing(
                    submission.state, student.former_since is not None, bool(submission.notice_id)
                ):
                    submission.state = "missing"
                    changed += 1
            (await session.get_one(AssignmentRecord, assignment_id)).state = "closed"
        await self._lock_folders()
        return changed

    async def _lock_folders(self) -> None:
        """Make the sharing permission of the folders of every closed Assignment, and of every
        returned Submission, read, so Students can still see what they handed in but cannot add to
        it. A failure is tried again."""
        async with sessions()() as session:
            unlocked = list(
                await session.scalars(
                    select(SubmissionRecord.id)
                    .join(AssignmentRecord, AssignmentRecord.id == SubmissionRecord.assignment_id)
                    .where(
                        or_(
                            AssignmentRecord.state == "closed", SubmissionRecord.state == "returned"
                        ),
                        SubmissionRecord.permission_id.is_not(None),
                        SubmissionRecord.locked.is_(False),
                    )
                )
            )
        for submission_id in unlocked:
            try:
                await self._lock(submission_id)
            except SignInRequired:
                raise
            except Exception:
                log.exception("folder of submission %s not locked", submission_id)

    async def _lock(self, submission_id: str) -> None:
        async with sessions()() as session:
            row = await session.get_one(SubmissionRecord, submission_id)
        try:
            await self._graph.send(
                "PATCH",
                f"/me/drive/items/{row.folder_id}/permissions/{row.permission_id}",
                {"roles": ["read"]},
            )
        except GraphError as error:
            if error.status != 404:  # a folder the Teacher deleted needs no lock
                raise
        async with sessions().begin() as session:
            (await session.get_one(SubmissionRecord, submission_id)).locked = True


def _touch(submission: SubmissionRecord, at: datetime) -> None:
    submission.changed_at = max(filter(None, [submission.changed_at, at]))
    submission.pending = True
