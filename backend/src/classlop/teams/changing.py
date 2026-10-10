"""Changing a Given Assignment through Graph: its times, its recipients, its Submissions and its
existence. GraphTeams inherits it."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from ulid import ULID

from classlop.shared import jobs, schedule, storage
from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.shared.settings import get_settings
from classlop.teams import amendments, assignments, lifecycle
from classlop.teams import submissions as rules
from classlop.teams.assignment_records import AssignmentRecord, SubmissionRecord
from classlop.teams.graph import GraphClient, GraphError
from classlop.teams.handin_records import HandinFileRecord
from classlop.teams.lifecycle import check_writable
from classlop.teams.types import Assignment, Class, Student, Submission

log = logging.getLogger(__name__)


class Changing:
    _graph: GraphClient
    _clock: Callable[[], datetime]

    if TYPE_CHECKING:

        async def get_class(self, class_id: str) -> Class: ...
        async def reschedule_reminder(self, assignment_id: str) -> None: ...
        async def _schedule_due(self, assignment_id: str) -> None: ...
        async def _read_delta(self) -> None: ...
        async def _discard(self, url: str) -> None: ...
        async def list_students(self, class_id: str) -> list[Student]: ...
        async def list_submissions(self, assignment_id: str) -> list[Submission]: ...
        async def _row(self, assignment_id: str) -> AssignmentRecord: ...
        async def _deliver(self, assignment_id: str) -> int: ...
        async def _save_assignment(self, assignment_id: str, **fields) -> None: ...

    async def change_times(
        self, assignment_id: str, due_at: datetime | None = None, close_at: datetime | None = None
    ) -> Assignment:
        before = Assignment.model_validate(await self._row(assignment_id), from_attributes=True)
        check_writable(await self.get_class(before.class_id))
        due, close = amendments.moved(before, due_at, close_at)
        after = before.model_copy(update={"due_at": due, "close_at": close})
        if due != before.due_at and after.post_id:
            await self._amend_post(after)
        await self._save_assignment(assignment_id, due_at=due, close_at=close)
        await self._recompute_late(after)
        await self.reschedule_reminder(assignment_id)
        await self._schedule_due(assignment_id)
        return after

    async def add_recipients(self, assignment_id: str, student_ids: list[str]) -> list[Submission]:
        row = await self._row(assignment_id)
        check_writable(await self.get_class(row.class_id))
        if row.state not in ("scheduled", "open"):
            raise ValueError("Students are added to a Scheduled or Open Assignment")
        chosen = assignments.recipients(await self.list_students(row.class_id), student_ids)
        return await self._enrol(row, chosen)

    async def _catch_up(self, class_id: str) -> None:
        """Whole-Class Assignments that are Open or Scheduled reach every current Student, so a
        Student who joined since is given theirs. Roster sync calls it."""
        async with sessions()() as session:
            rows = list(
                await session.scalars(
                    select(AssignmentRecord).where(
                        AssignmentRecord.class_id == class_id,
                        AssignmentRecord.whole_class,
                        AssignmentRecord.state.in_(["scheduled", "open"]),
                    )
                )
            )
        students = [s for s in await self.list_students(class_id) if not s.former_since]
        for row in rows:
            await self._enrol(row, students)

    async def _enrol(self, row: AssignmentRecord, students: list[Student]) -> list[Submission]:
        """A Submission for each of the Students without one, delivered at once to an Open
        Assignment (a Scheduled one's are delivered when it is posted)."""
        async with sessions().begin() as session:
            have = set(
                await session.scalars(
                    select(SubmissionRecord.student_id).where(
                        SubmissionRecord.assignment_id == row.id
                    )
                )
            )
            added = [
                SubmissionRecord(id=str(ULID()), assignment_id=row.id, student_id=s.id)
                for s in students
                if s.id not in have
            ]
            session.add_all(added)
        if added and row.state == "open" and await self._deliver(row.id):
            await jobs.enqueue(
                "teams.deliver_assignment",
                {"assignment_id": row.id},
                delay=assignments.RETRY_DELAY,
            )
        mine = {s.id for s in added}
        return [s for s in await self.list_submissions(row.id) if s.id in mine]

    async def excuse_submission(self, submission_id: str, reason: str | None = None) -> Submission:
        async with sessions()() as session:
            row = await session.get(SubmissionRecord, submission_id)
        if row is None:
            raise LookupError(submission_id)
        check_writable(await self.get_class((await self._row(row.assignment_id)).class_id))
        async with sessions().begin() as session:
            row = await session.get_one(SubmissionRecord, submission_id)
            row.state, row.excused_reason, row.pending = "excused", amendments.note(reason), False
            return Submission.model_validate(row, from_attributes=True)

    async def delete_assignment(self, assignment_id: str) -> None:
        row = await self._row(assignment_id)
        klass = await self.get_class(row.class_id)
        check_writable(klass)
        await self._read_delta()  # files uploaded since the last poll count as handed in
        submissions = await self.list_submissions(assignment_id)
        async with sessions()() as session:
            uploaded = set(
                await session.scalars(
                    select(HandinFileRecord.submission_id).where(
                        HandinFileRecord.submission_id.in_([s.id for s in submissions])
                    )
                )
            )
        amendments.check_deletable(submissions, uploaded)
        # Every step tolerates what is already gone, so a repeat finishes what one began.
        if row.post_id:
            teacher = get_settings().m365_teacher_oid
            post = f"/teams/{klass.team_id}/channels/{row.post_channel_id}/messages/{row.post_id}"
            try:
                await self._graph.request("POST", f"/users/{teacher}{post}/softDelete")
            except GraphError as error:
                if error.status != 404:
                    raise
        if row.folder_id:
            await self._discard(f"/me/drive/items/{row.folder_id}")
        for name in lifecycle.schedule_names(assignment_id):
            await schedule.cancel(name)
        if row.pdf_key:
            await asyncio.to_thread(storage.delete, row.pdf_key)
        for submission in submissions:
            await asyncio.to_thread(storage.delete_prefix, rules.prefix(submission.id))
        await self._tell_cancelled(row.title, submissions)
        async with sessions().begin() as session:
            await session.execute(delete(AssignmentRecord).where(AssignmentRecord.id == row.id))

    async def _tell_cancelled(self, title: str, submissions: list[Submission]) -> None:
        """A message to each Student the Assignment reached; one that fails is not tried again,
        as the Assignment is gone either way."""
        message = {"body": {"contentType": "html", "content": amendments.cancelled_html(title)}}
        for submission in submissions:
            if not (submission.chat_id and submission.notice_id):
                continue
            try:
                await self._graph.send("POST", f"/chats/{submission.chat_id}/messages", message)
            except SignInRequired:
                raise
            except Exception:
                log.exception("no cancellation sent for submission %s", submission.id)

    async def _amend_post(self, a: Assignment) -> None:
        """Correct the due time in the post and say so in its thread, which notifies Students."""
        klass = await self.get_class(a.class_id)
        url = f"/teams/{klass.team_id}/channels/{a.post_channel_id}/messages/{a.post_id}"
        attachments = (await self._graph.get(url))["attachments"]
        html = assignments.post_html(a, attachments[0]["id"])
        body = {"contentType": "html", "content": html}
        await self._graph.request("PATCH", url, json={"body": body, "attachments": attachments})
        reply = {"body": {"contentType": "html", "content": amendments.due_moved_html(a.due_at)}}
        await self._graph.send("POST", f"{url}/replies", reply)

    async def _recompute_late(self, a: Assignment) -> None:
        """A hand-in is Late against the due time as it now stands."""
        async with sessions().begin() as session:
            rows = await session.scalars(
                select(SubmissionRecord).where(
                    SubmissionRecord.assignment_id == a.id,
                    SubmissionRecord.state.in_(["handed_in", "graded"]),
                )
            )
            for row in rows:
                if row.handed_in_at:
                    row.late = amendments.is_late(row.handed_in_at, a.due_at)
