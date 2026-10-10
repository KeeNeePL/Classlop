"""Returning Feedback to Students through Graph: the PDF goes to the Teacher's OneDrive, is shared
to the Student read-only and is attached to a message in their 1:1 chat. GraphTeams inherits it.
When a Submission is returned is decided by `feedback.py`; grading's side is `grading.result`."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from ulid import ULID

from classlop import grading
from classlop.shared import jobs, schedule, storage
from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.teams import feedback, ids
from classlop.teams.assignment_records import AssignmentRecord, SubmissionRecord
from classlop.teams.feedback_records import FeedbackRecord
from classlop.teams.graph import GraphClient, attachment_id, html_body, or_gone
from classlop.teams.models import StudentRecord
from classlop.teams.types import Assignment, SubmissionState

log = logging.getLogger(__name__)


class Returning:
    _graph: GraphClient
    _clock: Callable[[], datetime]

    if TYPE_CHECKING:

        async def get_assignment(self, assignment_id: str) -> Assignment: ...
        async def _row(self, assignment_id: str) -> AssignmentRecord: ...
        async def _folder(self, parent: str | None, name: str) -> dict: ...
        async def _lock(self, submission_id: str) -> None: ...

    async def submission_graded(self, submission_id: str, handed_in_at: datetime) -> None:
        await self._consider(submission_id, handed_in_at)

    async def return_graded(self, assignment_id: str) -> int:
        await self._row(assignment_id)  # LookupError once its Class is deleted
        assignment = await self.get_assignment(assignment_id)
        async with sessions()() as session:
            graded = list(
                await session.scalars(
                    select(SubmissionRecord.id)
                    .where(
                        SubmissionRecord.assignment_id == assignment_id,
                        SubmissionRecord.state == "graded",
                    )
                    .order_by(SubmissionRecord.id)
                )
            )
        key, payload = feedback.common_mistakes_job(assignment)
        await jobs.enqueue("grading.common_mistakes", payload, key=key)
        returned = failed = 0
        for submission_id in graded:
            try:
                returned += await self._consider(submission_id)
            except SignInRequired:
                raise
            except Exception:
                log.exception("feedback of submission %s not returned", submission_id)
                failed += 1
        if failed:
            raise RuntimeError(f"{failed} Submissions not returned")
        return returned

    async def _schedule_due(self, assignment_id: str) -> None:
        """The job at the due time; a Given Assignment has one, moved when its due time is."""
        due = (await self._row(assignment_id)).due_at
        await schedule.at(
            feedback.schedule_name(assignment_id),
            feedback.due_at(due, self._clock()),
            "teams.assignment_due",
            {"assignment_id": assignment_id},
        )

    async def _consider(self, submission_id: str, handed_in_at: datetime | None = None) -> int:
        """Act on the current result of a Submission's hand-in: mark it Graded, return it or send
        a correction. Returns 1 if a message went out."""
        async with sessions()() as session:
            row = await session.get(SubmissionRecord, submission_id)
        if row is None:
            raise LookupError(submission_id)
        if row.handed_in_at is None or handed_in_at not in (None, row.handed_in_at):
            return 0
        found = await grading.result(ids.as_uuid(submission_id), row.handed_in_at)
        if found is None or found.status != "graded":
            return 0
        assignment = await self.get_assignment(row.assignment_id)
        sent = await self._last_sent(submission_id)
        action = feedback.step(
            state=row.state,
            late=row.late,
            due_at=assignment.due_at,
            now=self._clock(),
            held=found.held,
            pdf_key=found.pdf_key or "",
            sent=sent,
        )
        if action in ("mark", "return") and row.state == "handed_in":
            await self._set_state(submission_id, "graded", expect="handed_in")
        if action in ("return", "correct"):
            await self._send(row, assignment, found, corrected=action == "correct")
            return 1
        return 0

    async def _last_sent(self, submission_id: str) -> str | None:
        async with sessions()() as session:
            return await session.scalar(
                select(FeedbackRecord.pdf_key)
                .where(
                    FeedbackRecord.submission_id == submission_id,
                    FeedbackRecord.message_id.is_not(None),
                )
                .order_by(FeedbackRecord.sent_at.desc())
                .limit(1)
            )

    async def _set_state(
        self, submission_id: str, state: SubmissionState, *, expect: SubmissionState
    ) -> None:
        async with sessions().begin() as session:
            row = await session.get_one(SubmissionRecord, submission_id)
            if row.state == expect:
                row.state = state

    async def _send(
        self,
        submission: SubmissionRecord,
        assignment: Assignment,
        found: grading.Result,
        *,
        corrected: bool,
    ) -> None:
        """Every step records what it did, so a repeat resumes where one stopped and a message
        goes out once."""
        key = found.pdf_key or ""
        async with sessions().begin() as session:
            await session.execute(
                insert(FeedbackRecord)
                .values(id=str(ULID()), submission_id=submission.id, pdf_key=key)
                .on_conflict_do_nothing(index_elements=["submission_id", "pdf_key"])
            )
        async with sessions()() as session:
            sent = await session.scalar(
                select(FeedbackRecord).where(
                    FeedbackRecord.submission_id == submission.id, FeedbackRecord.pdf_key == key
                )
            )
            student = await session.get_one(StudentRecord, submission.student_id)
        assert sent
        if sent.message_id:
            return
        if not submission.chat_id:
            raise RuntimeError("the Student has no chat yet")
        if key and sent.item_id is None:
            await self._upload(sent, key, assignment, student)
        if key and not sent.shared:
            await self._graph.send(
                "POST",
                f"/me/drive/items/{sent.item_id}/invite",
                {
                    "recipients": [{"objectId": student.user_id}],
                    "requireSignIn": True,
                    "sendInvitation": False,
                    "roles": ["read"],
                },
            )
            await self._save_feedback(sent, shared=True)
        body: dict = {
            "body": html_body(
                feedback.message_html(assignment, found.comment, corrected, sent.attachment_id)
            )
        }
        if key:
            body["attachments"] = [
                {
                    "id": sent.attachment_id,
                    "contentType": "reference",
                    "contentUrl": sent.web_url,
                    "name": feedback.attachment_name(assignment),
                }
            ]
        message = await self._graph.send("POST", f"/chats/{submission.chat_id}/messages", body)
        await self._save_feedback(sent, message_id=message["id"], sent_at=self._clock())
        if corrected:
            return
        await self._set_state(submission.id, "returned", expect="graded")
        try:
            if submission.permission_id:
                await self._lock(submission.id)
        except SignInRequired:
            raise
        except Exception:
            log.exception("folder of submission %s not locked", submission.id)

    async def _upload(
        self, sent: FeedbackRecord, key: str, assignment: Assignment, student: StudentRecord
    ) -> None:
        pdf = await asyncio.to_thread(storage.get, key)
        folder = await self._feedback_folder(assignment.id)
        name = quote(feedback.file_name(student.display_name))
        file = (
            await self._graph.request(
                "PUT",
                f"/me/drive/items/{folder}:/{name}:/content",
                content=pdf,
                params={"@microsoft.graph.conflictBehavior": "rename"},
                headers={"Content-Type": "application/pdf"},
            )
        ).json()
        await self._save_feedback(
            sent,
            item_id=file["id"],
            attachment_id=attachment_id(file),
            web_url=file["webUrl"],
        )

    async def _feedback_folder(self, assignment_id: str) -> str:
        """`Classlop/<Class>/<Assignment>/Feedback`, deleted with the Assignment's folder."""
        parent = (await self._row(assignment_id)).folder_id
        if parent is None:
            raise RuntimeError("the Assignment has no folder")
        found = await or_gone(self._graph.get(f"/me/drive/items/{parent}:/{feedback.FOLDER}"))
        return (found or await self._folder(parent, feedback.FOLDER))["id"]

    async def _save_feedback(self, record: FeedbackRecord, **fields) -> None:
        async with sessions().begin() as session:
            row = await session.get_one(FeedbackRecord, record.id)
            for name, value in fields.items():
                setattr(row, name, value)
                setattr(record, name, value)
