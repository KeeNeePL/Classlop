"""Giving an Assignment through Graph: the post in General and, per Student, a private folder in
the Teacher's OneDrive and a chat message. GraphTeams inherits it."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import quote

from sqlalchemy import delete, select
from ulid import ULID

from classlop import items
from classlop.shared import jobs, schedule, storage
from classlop.shared.db import sessions
from classlop.shared.jobs import SignInRequired
from classlop.shared.settings import get_settings
from classlop.teams import assignments, ids
from classlop.teams.assignment_records import AssignmentRecord, SubmissionRecord
from classlop.teams.graph import BASE, GraphClient, GraphError
from classlop.teams.lifecycle import check_writable, writable
from classlop.teams.models import StudentRecord
from classlop.teams.types import Assignment, AssignmentSpec, Class, Student, Submission

log = logging.getLogger(__name__)


def _assignment(row: AssignmentRecord) -> Assignment:
    return Assignment.model_validate(row, from_attributes=True)


class Giving:
    _graph: GraphClient
    _clock: Callable[[], datetime]

    if TYPE_CHECKING:

        async def get_class(self, class_id: str) -> Class: ...
        async def list_students(self, class_id: str) -> list[Student]: ...
        async def sync_roster(self, class_id: str) -> None: ...
        async def reschedule_reminder(self, assignment_id: str) -> None: ...

    @writable
    async def give_assignment(
        self, class_id: str, spec: AssignmentSpec, items_pdf: bytes, when: datetime | None = None
    ) -> Assignment:
        assignments.check(spec)
        assignments.check_time(when, self._clock())
        await self.sync_roster(class_id)
        chosen = assignments.recipients(await self.list_students(class_id), spec.student_ids)
        row = AssignmentRecord(
            id=str(ULID()),
            class_id=class_id,
            title=spec.title.strip(),
            type=spec.type,
            state="draft",
            due_at=spec.due_at,
            close_at=spec.close_at,
            reminder_on=spec.reminder_on,
            whole_class=spec.student_ids is None,
            item_ids=spec.item_ids,
            item_versions=[],
        )
        key = row.pdf_key = assignments.pdf_key(row.id)
        await asyncio.to_thread(storage.put, key, items_pdf, "application/pdf")
        async with sessions().begin() as session:
            session.add(row)
            session.add_all(
                SubmissionRecord(id=str(ULID()), assignment_id=row.id, student_id=s.id)
                for s in chosen
            )
        if when is not None:
            return await self._schedule(row.id, when)
        try:
            return await self._publish(row.id)
        except Exception:
            # Nothing was Given: the Teacher tries again from scratch.
            async with sessions().begin() as session:
                await session.execute(
                    delete(AssignmentRecord).where(
                        AssignmentRecord.id == row.id, AssignmentRecord.post_id.is_(None)
                    )
                )
            raise

    async def give_again(self, assignment_id: str, when: datetime | None = None) -> Assignment:
        row = await self._row(assignment_id)
        if row.state != "draft":
            raise ValueError("only a Draft is given again")
        check_writable(await self.get_class(row.class_id))
        assignments.check_time(when, self._clock())
        await self._save_assignment(assignment_id, give_failed_at=None)
        if when is None:
            return await self._publish(assignment_id)
        return await self._schedule(assignment_id, when)

    async def publish_scheduled(self, assignment_id: str, last_try: bool = False) -> Assignment:
        """At the scheduled time. If the post fails on the job's last try, the Assignment returns
        to Draft with `give_failed_at` set, unless Teams accepted the post meanwhile."""
        row = await self._row(assignment_id)
        if row.state not in ("scheduled", "open"):
            return _assignment(row)
        try:
            return await self._publish(assignment_id)
        except SignInRequired:
            raise
        except Exception:
            if not last_try or (await self._row(assignment_id)).post_id is not None:
                raise
            log.exception("assignment %s could not be given", assignment_id)
            await self._save_assignment(
                assignment_id, state="draft", give_failed_at=self._clock(), publish_at=None
            )
            return await self.get_assignment(assignment_id)

    async def list_failed_gives(self) -> list[Assignment]:
        async with sessions()() as session:
            rows = await session.scalars(
                select(AssignmentRecord)
                .where(AssignmentRecord.give_failed_at.is_not(None))
                .where(AssignmentRecord.state == "draft")
                .order_by(AssignmentRecord.give_failed_at, AssignmentRecord.id)
            )
            return [_assignment(r) for r in rows]

    async def _schedule(self, assignment_id: str, when: datetime) -> Assignment:
        """Given at once, so the Items freeze now; the post follows at `when`."""
        row = await self._row(assignment_id)
        now = row.given_at or self._clock()
        versions = row.item_versions or await items.give(
            row.item_ids, ids.as_uuid(row.id), ids.as_uuid(row.class_id), now
        )
        await schedule.at(
            assignments.schedule_name(assignment_id),
            when,
            "teams.give_assignment",
            {"assignment_id": assignment_id},
        )
        await self._save_assignment(
            assignment_id, state="scheduled", given_at=now, item_versions=versions, publish_at=when
        )
        await self.reschedule_reminder(assignment_id)
        return await self.get_assignment(assignment_id)

    async def get_assignment(self, assignment_id: str) -> Assignment:
        return _assignment(await self._row(assignment_id))

    async def list_assignments(self, class_id: str) -> list[Assignment]:
        async with sessions()() as session:
            rows = await session.scalars(
                select(AssignmentRecord)
                .where(AssignmentRecord.class_id == class_id)
                .order_by(AssignmentRecord.due_at, AssignmentRecord.id)
            )
            return [_assignment(r) for r in rows]

    async def list_submissions(self, assignment_id: str) -> list[Submission]:
        async with sessions()() as session:
            rows = await session.scalars(
                select(SubmissionRecord)
                .where(SubmissionRecord.assignment_id == assignment_id)
                .order_by(SubmissionRecord.id)
            )
            return [Submission.model_validate(r, from_attributes=True) for r in rows]

    async def _publish(self, assignment_id: str) -> Assignment:
        """Post in General, which Gives the Assignment and freezes its Items, then deliver it to
        the Students. Every step records what it did, so a repeat resumes where one stopped."""
        row = await self._row(assignment_id)
        if row.post_id is None:
            await self._post(row)
            row = await self._row(assignment_id)
        if not row.item_versions:
            versions = await items.give(
                row.item_ids,
                ids.as_uuid(row.id),
                ids.as_uuid(row.class_id),
                row.given_at or self._clock(),
            )
            await self._save_assignment(row.id, item_versions=versions)
        if await self._deliver(row.id):
            await jobs.enqueue(
                "teams.deliver_assignment",
                {"assignment_id": row.id},
                delay=assignments.RETRY_DELAY,
            )
        await self.reschedule_reminder(row.id)
        return await self.get_assignment(row.id)

    async def deliver_assignment(self, assignment_id: str) -> int:
        return await self._deliver(assignment_id)

    async def _row(self, assignment_id: str) -> AssignmentRecord:
        async with sessions()() as session:
            row = await session.get(AssignmentRecord, assignment_id)
        if row is None:
            raise LookupError(assignment_id)
        return row

    async def _save_assignment(self, assignment_id: str, **fields) -> None:
        async with sessions().begin() as session:
            row = await session.get_one(AssignmentRecord, assignment_id)
            for name, value in fields.items():
                setattr(row, name, value)

    async def _post(self, row: AssignmentRecord) -> None:
        """The post in General with the Items PDF attached: the file goes to the channel's files
        folder, the message references it."""
        assert row.pdf_key
        pdf = await asyncio.to_thread(storage.get, row.pdf_key)
        klass = await self.get_class(row.class_id)
        channel = f"/teams/{klass.team_id}/channels/{klass.general_channel_id}"
        folder = await self._graph.get(f"{channel}/filesFolder")
        name = quote(assignments.safe(row.title) + ".pdf")
        file = (
            await self._graph.request(
                "PUT",
                f"/drives/{folder['parentReference']['driveId']}/items/{folder['id']}:/{name}:/content",
                content=pdf,
                params={"@microsoft.graph.conflictBehavior": "rename"},
                headers={"Content-Type": "application/pdf"},
            )
        ).json()
        attachment = file["eTag"].strip('"{').split("}")[0]  # the GUID in "{GUID},version"
        post = await self._graph.send(
            "POST",
            f"{channel}/messages",
            {
                "body": {
                    "contentType": "html",
                    "content": assignments.post_html(_assignment(row), attachment),
                },
                "attachments": [
                    {
                        "id": attachment,
                        "contentType": "reference",
                        "contentUrl": file["webUrl"],
                        "name": file["name"],
                    }
                ],
            },
        )
        await self._save_assignment(
            row.id,
            state="open",
            given_at=row.given_at or self._clock(),
            post_id=post["id"],
            post_channel_id=klass.general_channel_id,
        )

    async def _deliver(self, assignment_id: str) -> int:
        """Folder, sharing and chat message for each Student still without them. A failure for
        one Student leaves them waiting without stopping the others; returns how many wait."""
        row = await self._row(assignment_id)
        async with sessions()() as session:
            waiting = list(
                await session.execute(
                    select(SubmissionRecord, StudentRecord)
                    .join(StudentRecord, StudentRecord.id == SubmissionRecord.student_id)
                    .where(
                        SubmissionRecord.assignment_id == assignment_id,
                        SubmissionRecord.notice_id.is_(None),
                        StudentRecord.former_since.is_(None),
                    )
                    .order_by(SubmissionRecord.id)
                )
            )
        if not waiting:
            return 0
        try:
            folder_id = row.folder_id or await self._assignment_folder(row)
        except Exception as error:
            if isinstance(error, SignInRequired):
                raise
            log.exception("no folder for assignment %s", assignment_id)
            return len(waiting)
        left = 0
        for submission, student in waiting:
            try:
                await self._deliver_one(_assignment(row), folder_id, submission, student)
            except SignInRequired:
                raise
            except Exception:
                log.exception("assignment %s not delivered to %s", assignment_id, student.id)
                left += 1
        return left

    async def _assignment_folder(self, row: AssignmentRecord) -> str:
        """`Classlop/<Class>/<Assignment>` in the Teacher's OneDrive; Students' folders go in it."""
        klass = await self.get_class(row.class_id)
        parent, walked = None, []
        for name in ("Classlop", assignments.safe(klass.name)):
            walked.append(quote(name))
            try:
                folder = await self._graph.get(f"/me/drive/root:/{'/'.join(walked)}")
            except GraphError as error:
                if error.status != 404:
                    raise
                folder = await self._folder(parent, name)
            parent = folder["id"]
        folder = await self._folder(parent, assignments.safe(row.title))
        await self._save_assignment(row.id, folder_id=folder["id"])
        return folder["id"]

    async def _folder(self, parent: str | None, name: str) -> dict:
        """A new folder under `parent` (the root if None), renamed rather than merged into one
        that exists."""
        where = f"/me/drive/items/{parent}" if parent else "/me/drive/root"
        return await self._graph.send(
            "POST",
            f"{where}/children",
            {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"},
        )

    async def _deliver_one(
        self,
        assignment: Assignment,
        folder_id: str,
        submission: SubmissionRecord,
        student: StudentRecord,
    ) -> None:
        if submission.folder_id is None:
            folder = await self._folder(folder_id, assignments.safe(student.display_name))
            await self._save_submission(
                submission, folder_id=folder["id"], folder_url=folder["webUrl"]
            )
        if submission.permission_id is None:
            shared = await self._graph.send(
                "POST",
                f"/me/drive/items/{submission.folder_id}/invite",
                {
                    "recipients": [{"objectId": student.user_id}],
                    "requireSignIn": True,
                    "sendInvitation": False,
                    "roles": ["write"],
                },
            )
            await self._save_submission(submission, permission_id=shared["value"][0]["id"])
        if submission.chat_id is None:
            chat = await self._graph.send(
                "POST",
                "/chats",
                {
                    "chatType": "oneOnOne",
                    "members": [
                        _chat_member(get_settings().m365_teacher_oid),
                        _chat_member(student.user_id),
                    ],
                },
            )
            await self._save_submission(submission, chat_id=chat["id"])
        notice = await self._graph.send(
            "POST",
            f"/chats/{submission.chat_id}/messages",
            {
                "body": {
                    "contentType": "html",
                    "content": assignments.notice_html(assignment, submission.folder_url or ""),
                }
            },
        )
        await self._save_submission(submission, notice_id=notice["id"])

    async def _save_submission(self, submission: SubmissionRecord, **fields) -> None:
        async with sessions().begin() as session:
            row = await session.get_one(SubmissionRecord, submission.id)
            for name, value in fields.items():
                setattr(row, name, value)
                setattr(submission, name, value)


def _chat_member(user_id: str) -> dict:
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "roles": ["owner"],
        "user@odata.bind": f"{BASE}/users('{user_id}')",
    }
