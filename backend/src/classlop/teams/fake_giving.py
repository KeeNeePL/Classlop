"""Giving an Assignment in memory, for FakeTeams. It follows giving.py step by step; the rules
and the words are the shared ones in assignments.py."""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple

from ulid import ULID

from classlop import items
from classlop.shared import jobs, schedule
from classlop.shared.jobs import SignInRequired
from classlop.teams import assignments, ids
from classlop.teams.lifecycle import check_writable, writable
from classlop.teams.types import Assignment, AssignmentSpec, Class, Student, Submission


class Post(NamedTuple):
    """A post in a team's channel: its HTML and the files attached, by name."""

    id: str
    html: str
    files: dict[str, bytes]


class Share(NamedTuple):
    """A folder of the Teacher's OneDrive shared with a Student."""

    path: str
    role: str
    url: str


class FakeGiving:
    _clock: Callable[[], datetime]
    _teams: dict[str, dict]

    if TYPE_CHECKING:

        def _require_sign_in(self) -> None: ...
        async def get_class(self, class_id: str) -> Class: ...
        async def list_students(self, class_id: str) -> list[Student]: ...
        async def sync_roster(self, class_id: str) -> None: ...

    def _init_giving(self) -> None:
        self._assignments: dict[str, Assignment] = {}
        self._submissions: dict[str, dict[str, Submission]] = {}  # by Assignment, then Student
        self._pdfs: dict[str, bytes] = {}
        self._posts: dict[str, list[Post]] = {}
        self._folders: set[str] = set()
        self._assignment_dirs: dict[str, str] = {}
        self._shares: dict[str, list[Share]] = {}  # by Student's user id
        self._chat_log: dict[str, list[str]] = {}  # by Student's user id
        self._rejected: set[str] = set()

    # What a test sets up and inspects, as FakeGraph's.
    def reject_chats(self, user_id: str) -> None:
        self._rejected.add(user_id)

    def accept_chats(self, user_id: str) -> None:
        self._rejected.discard(user_id)

    def reject_posts(self, team_id: str) -> None:
        self._rejected.add(team_id)

    def accept_posts(self, team_id: str) -> None:
        self._rejected.discard(team_id)

    def channel_posts(self, team_id: str) -> list[Post]:
        return self._posts.get(team_id, [])

    def shared_with(self, user_id: str) -> list[Share]:
        return self._shares.get(user_id, [])

    def chat_messages(self, user_id: str) -> list[str]:
        return self._chat_log.get(user_id, [])

    def invitation_emails(self) -> int:
        return 0

    @writable
    async def give_assignment(
        self, class_id: str, spec: AssignmentSpec, items_pdf: bytes, when: datetime | None = None
    ) -> Assignment:
        self._require_sign_in()
        assignments.check(spec)
        assignments.check_time(when, self._clock())
        await self.sync_roster(class_id)
        chosen = assignments.recipients(await self.list_students(class_id), spec.student_ids)
        given = Assignment(
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
        )
        self._assignments[given.id], self._pdfs[given.id] = given, items_pdf
        self._submissions[given.id] = {
            s.id: Submission(id=str(ULID()), assignment_id=given.id, student_id=s.id)
            for s in chosen
        }
        if when is not None:
            return await self._schedule(given.id, when)
        try:
            return await self._publish(given.id)
        except Exception:
            if self._assignments[given.id].post_id is None:
                del self._assignments[given.id], self._submissions[given.id]
            raise

    async def give_again(self, assignment_id: str, when: datetime | None = None) -> Assignment:
        self._require_sign_in()
        if self._assignments[assignment_id].state != "draft":
            raise ValueError("only a Draft is given again")
        check_writable(await self.get_class(self._assignments[assignment_id].class_id))
        assignments.check_time(when, self._clock())
        self._save(assignment_id, give_failed_at=None)
        if when is None:
            return await self._publish(assignment_id)
        return await self._schedule(assignment_id, when)

    async def publish_scheduled(self, assignment_id: str, last_try: bool = False) -> Assignment:
        self._require_sign_in()
        if self._assignments[assignment_id].state not in ("scheduled", "open"):
            return self._assignments[assignment_id]
        try:
            return await self._publish(assignment_id)
        except SignInRequired:
            raise
        except Exception:
            if not last_try or self._assignments[assignment_id].post_id is not None:
                raise
            return self._save(
                assignment_id, state="draft", give_failed_at=self._clock(), publish_at=None
            )

    async def list_failed_gives(self) -> list[Assignment]:
        found = [
            a
            for a in self._assignments.values()
            if a.state == "draft" and a.give_failed_at is not None
        ]
        return sorted(found, key=lambda a: (a.give_failed_at, a.id))

    async def get_assignment(self, assignment_id: str) -> Assignment:
        return self._assignments[assignment_id]

    async def list_assignments(self, class_id: str) -> list[Assignment]:
        found = [a for a in self._assignments.values() if a.class_id == class_id]
        return sorted(found, key=lambda a: (a.due_at, a.id))

    async def list_submissions(self, assignment_id: str) -> list[Submission]:
        return sorted(self._submissions[assignment_id].values(), key=lambda s: s.id)

    def _save(self, assignment_id: str, **fields) -> Assignment:
        saved = self._assignments[assignment_id].model_copy(update=fields)
        self._assignments[assignment_id] = saved
        return saved

    async def _schedule(self, assignment_id: str, when: datetime) -> Assignment:
        given = self._assignments[assignment_id]
        now = given.given_at or self._clock()
        versions = given.item_versions or await items.give(
            given.item_ids, ids.as_uuid(given.id), ids.as_uuid(given.class_id), now
        )
        await schedule.at(
            assignments.schedule_name(assignment_id),
            when,
            "teams.give_assignment",
            {"assignment_id": assignment_id},
        )
        return self._save(
            assignment_id, state="scheduled", given_at=now, item_versions=versions, publish_at=when
        )

    async def _publish(self, assignment_id: str) -> Assignment:
        given = self._assignments[assignment_id]
        if given.post_id is None:
            klass = await self.get_class(given.class_id)
            if klass.team_id in self._rejected:
                raise RuntimeError("the post was refused")
            name = f"{assignments.safe(given.title)}.pdf"
            post = Post(
                str(uuid.uuid4()),
                assignments.post_html(given, str(uuid.uuid4())),
                {name: self._pdfs[assignment_id]},
            )
            self._posts.setdefault(klass.team_id, []).append(post)
            given = self._save(
                assignment_id,
                state="open",
                given_at=given.given_at or self._clock(),
                post_id=post.id,
                post_channel_id=klass.general_channel_id,
            )
        if not given.item_versions:
            versions = await items.give(
                given.item_ids,
                ids.as_uuid(given.id),
                ids.as_uuid(given.class_id),
                given.given_at or self._clock(),
            )
            self._save(assignment_id, item_versions=versions)
        if await self._deliver(assignment_id):
            await jobs.enqueue(
                "teams.deliver_assignment",
                {"assignment_id": assignment_id},
                delay=assignments.RETRY_DELAY,
            )
        return self._assignments[assignment_id]

    async def deliver_assignment(self, assignment_id: str) -> int:
        self._require_sign_in()
        return await self._deliver(assignment_id)

    def _folder(self, parent: str, name: str) -> str:
        """The path of a new folder, renamed rather than merged into one that exists."""
        path, n = f"{parent}/{name}", 0
        while path in self._folders:
            n += 1
            path = f"{parent}/{name} {n}"
        self._folders.add(path)
        return path

    async def _deliver(self, assignment_id: str) -> int:
        """As Giving._deliver: returns how many Students are still waiting."""
        given = self._assignments[assignment_id]
        klass = await self.get_class(given.class_id)
        students = {s.id: s for s in await self.list_students(given.class_id)}
        waiting = [
            s
            for s in self._submissions[assignment_id].values()
            if s.notice_id is None and not students[s.student_id].former_since
        ]
        if not waiting:
            return 0
        if assignment_id not in self._assignment_dirs:
            self._assignment_dirs[assignment_id] = self._folder(
                f"Classlop/{assignments.safe(klass.name)}", assignments.safe(given.title)
            )
        left = 0
        for submission in waiting:
            try:
                self._deliver_one(given, submission, students[submission.student_id])
            except SignInRequired:
                raise
            except Exception:
                left += 1
        return left

    def _deliver_one(self, given: Assignment, submission: Submission, student: Student) -> None:
        if submission.folder_id is None:
            path = self._folder(
                self._assignment_dirs[given.id], assignments.safe(student.display_name)
            )
            submission = self._update(submission, folder_id=path, folder_url=_url())
        if submission.permission_id is None:
            self._shares.setdefault(student.user_id, []).append(
                Share(submission.folder_id or "", "write", submission.folder_url or "")
            )
            submission = self._update(submission, permission_id=str(uuid.uuid4()))
        if student.user_id in self._rejected:
            raise RuntimeError("the chat was refused")
        submission = self._update(submission, chat_id=submission.chat_id or str(uuid.uuid4()))
        self._chat_log.setdefault(student.user_id, []).append(
            assignments.notice_html(given, submission.folder_url or "")
        )
        self._update(submission, notice_id=str(uuid.uuid4()))

    def _update(self, submission: Submission, **fields) -> Submission:
        updated = submission.model_copy(update=fields)
        self._submissions[submission.assignment_id][submission.student_id] = updated
        return updated


def _url() -> str:
    return f"https://onedrive.example.org/{uuid.uuid4().hex}"
