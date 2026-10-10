"""Changing a Given Assignment through Graph: its times, its recipients, its Submissions and its
existence. GraphTeams inherits it."""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from ulid import ULID

from classlop.shared import jobs
from classlop.shared.db import sessions
from classlop.teams import amendments, assignments
from classlop.teams.assignment_records import AssignmentRecord, SubmissionRecord
from classlop.teams.graph import GraphClient
from classlop.teams.lifecycle import check_writable
from classlop.teams.types import Assignment, Class, Student, Submission


class Changing:
    _graph: GraphClient
    _clock: Callable[[], datetime]

    if TYPE_CHECKING:

        async def get_class(self, class_id: str) -> Class: ...
        async def get_assignment(self, assignment_id: str) -> Assignment: ...
        async def list_students(self, class_id: str) -> list[Student]: ...
        async def list_submissions(self, assignment_id: str) -> list[Submission]: ...
        async def _row(self, assignment_id: str) -> AssignmentRecord: ...
        async def _deliver(self, assignment_id: str) -> int: ...
        async def _save_assignment(self, assignment_id: str, **fields) -> None: ...

    async def change_times(
        self, assignment_id: str, due_at: datetime | None = None, close_at: datetime | None = None
    ) -> Assignment:
        before = await self.get_assignment(assignment_id)
        check_writable(await self.get_class(before.class_id))
        due, close = amendments.moved(before, due_at, close_at)
        after = before.model_copy(update={"due_at": due, "close_at": close})
        if due != before.due_at and after.post_id:
            await self._amend_post(after)
        await self._save_assignment(assignment_id, due_at=due, close_at=close)
        await self._recompute_late(after)
        await amendments.reschedule_reminder(after)
        await amendments.reschedule_return(after)
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
        check_writable(await self.get_class((await self.get_assignment(row.assignment_id)).class_id))
        async with sessions().begin() as session:
            row = await session.get_one(SubmissionRecord, submission_id)
            row.state, row.excused_reason, row.pending = "excused", amendments.note(reason), False
            return Submission.model_validate(row, from_attributes=True)

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
                row.late = amendments.is_late(row.handed_in_at, a.due_at)
