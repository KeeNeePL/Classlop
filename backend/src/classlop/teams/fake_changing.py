"""Changing a Given Assignment in memory, for FakeTeams. It follows changing.py; the rules and the
words are the shared ones in amendments.py."""

import asyncio
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from ulid import ULID

from classlop.shared import jobs, schedule, storage
from classlop.teams import amendments, assignments, lifecycle
from classlop.teams import submissions as rules
from classlop.teams.fake_giving import Post
from classlop.teams.fake_handins import Hand
from classlop.teams.lifecycle import check_writable
from classlop.teams.types import Assignment, Class, Student, Submission


class FakeChanging:
    _assignments: dict[str, Assignment]
    _submissions: dict[str, dict[str, Submission]]
    _posts: dict[str, list[Post]]
    _rejected: set[str]
    _pdfs: dict[str, bytes]
    _chat_log: dict[str, list[str]]
    _hands: dict[str, Hand]
    _assignment_dirs: dict[str, str]

    if TYPE_CHECKING:

        def _require_sign_in(self) -> None: ...
        async def reschedule_reminder(self, assignment_id: str) -> None: ...
        def _read(self) -> None: ...
        def _drop_folders(self, path: str | None) -> None: ...
        def _hand(self, submission: Submission) -> Hand: ...
        def _save(self, assignment_id: str, **fields) -> Assignment: ...
        def _update(self, submission: Submission, **fields) -> Submission: ...
        async def get_class(self, class_id: str) -> Class: ...
        async def list_students(self, class_id: str) -> list[Student]: ...
        async def _of_class(self, class_id: str) -> list[Assignment]: ...
        async def _deliver(self, assignment_id: str) -> int: ...

    def _init_changing(self) -> None:
        self._replies: dict[str, list[str]] = {}  # by post id

    # What a test inspects, as FakeGraph's.
    def replies_to(self, post_id: str) -> list[str]:
        return self._replies.get(post_id, [])

    def delete_post(self, team_id: str, post_id: str) -> None:
        """A post deleted in Teams, as FakeGraph's."""
        self._posts[team_id] = [p for p in self._posts[team_id] if p.id != post_id]

    async def delete_assignment(self, assignment_id: str) -> None:
        self._require_sign_in()
        given = self._assignments[assignment_id]
        klass = await self.get_class(given.class_id)
        check_writable(klass)
        self._read()
        submissions = list(self._submissions[assignment_id].values())
        uploaded = {s.id for s in submissions if self._hand(s).files}
        amendments.check_deletable(submissions, uploaded)
        if given.post_id:
            if klass.team_id in self._rejected:
                raise RuntimeError("the post was refused")
            self.delete_post(klass.team_id, given.post_id)
        self._drop_folders(self._assignment_dirs.pop(assignment_id, None))
        for name in lifecycle.schedule_names(assignment_id):
            await schedule.cancel(name)
        students = {s.id: s for s in await self.list_students(given.class_id)}
        for submission in submissions:
            await asyncio.to_thread(storage.delete_prefix, rules.prefix(submission.id))
            user_id = students[submission.student_id].user_id
            if submission.chat_id and submission.notice_id and user_id not in self._rejected:
                html = amendments.cancelled_html(given.title)
                self._chat_log.setdefault(user_id, []).append(html)
            self._hands.pop(submission.id, None)
        del self._assignments[assignment_id], self._submissions[assignment_id]
        del self._pdfs[assignment_id]

    async def add_recipients(self, assignment_id: str, student_ids: list[str]) -> list[Submission]:
        self._require_sign_in()
        given = self._assignments[assignment_id]
        check_writable(await self.get_class(given.class_id))
        if given.state not in ("scheduled", "open"):
            raise ValueError("Students are added to a Scheduled or Open Assignment")
        chosen = assignments.recipients(await self.list_students(given.class_id), student_ids)
        return await self._enrol(given, chosen)

    async def _catch_up(self, class_id: str) -> None:
        current = [s for s in await self.list_students(class_id) if not s.former_since]
        for given in await self._of_class(class_id):
            if given.whole_class and given.state in ("scheduled", "open"):
                await self._enrol(given, current)

    async def _enrol(self, given: Assignment, students: list[Student]) -> list[Submission]:
        have = self._submissions[given.id]
        added = [
            Submission(id=str(ULID()), assignment_id=given.id, student_id=s.id)
            for s in students
            if s.id not in have
        ]
        have.update({s.student_id: s for s in added})
        if added and given.state == "open" and await self._deliver(given.id):
            await jobs.enqueue(
                "teams.deliver_assignment",
                {"assignment_id": given.id},
                delay=assignments.RETRY_DELAY,
            )
        return [self._submissions[given.id][s.student_id] for s in added]

    def _submission(self, submission_id: str) -> Submission:
        for by_student in self._submissions.values():
            for submission in by_student.values():
                if submission.id == submission_id:
                    return submission
        raise LookupError(submission_id)

    async def excuse_submission(self, submission_id: str, reason: str | None = None) -> Submission:
        self._require_sign_in()
        submission = self._submission(submission_id)
        check_writable(await self.get_class(self._assignments[submission.assignment_id].class_id))
        self._hand(submission).pending = False
        return self._update(submission, state="excused", excused_reason=amendments.note(reason))

    async def change_times(
        self, assignment_id: str, due_at: datetime | None = None, close_at: datetime | None = None
    ) -> Assignment:
        self._require_sign_in()
        before = self._assignments[assignment_id]
        check_writable(await self.get_class(before.class_id))
        due, close = amendments.moved(before, due_at, close_at)
        after = before.model_copy(update={"due_at": due, "close_at": close})
        if due != before.due_at and after.post_id:
            klass = await self.get_class(after.class_id)
            if klass.team_id in self._rejected:
                raise RuntimeError("the post was refused")
            posts = self._posts[klass.team_id]
            n = next(n for n, p in enumerate(posts) if p.id == after.post_id)
            html = assignments.post_html(after, str(uuid.uuid4()))
            posts[n] = posts[n]._replace(html=html)
            self._replies.setdefault(after.post_id, []).append(amendments.due_moved_html(due))
        self._save(assignment_id, due_at=due, close_at=close)
        for submission in self._submissions[assignment_id].values():
            if submission.state in ("handed_in", "graded") and submission.handed_in_at:
                late = amendments.is_late(submission.handed_in_at, due)
                self._update(submission, late=late)
        await self.reschedule_reminder(assignment_id)
        await amendments.reschedule_return(after)
        return after
