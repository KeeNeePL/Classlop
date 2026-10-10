"""Deleting a Class, and a team deleted in Teams, in memory for FakeTeams. It follows
lifecycle.py; the rules are the shared ones there."""

import asyncio
from collections.abc import Callable
from datetime import date, datetime
from typing import TYPE_CHECKING

from classlop.shared import schedule, storage
from classlop.teams import lifecycle, submissions
from classlop.teams.service import WARSAW
from classlop.teams.types import Assignment, Class, Lesson, Student, Submission


class FakeLifecycle:
    _clock: Callable[[], datetime]
    _teams: dict[str, dict]
    _classes: dict[str, Class]
    _students: dict[str, dict[str, Student]]
    _series: dict[str, list[list]]
    _singles: dict[str, list[Lesson]]
    _events: dict[str, dict]
    _placed: dict[str, dict]
    _seen: dict[str, dict]
    _links: dict[str, dict[str, str]]
    _assignments: dict[str, Assignment]
    _submissions: dict[str, dict[str, Submission]]
    _pdfs: dict[str, bytes]
    _assignment_dirs: dict[str, str]
    _folders: set[str]
    _shares: dict[str, list]
    _drive: dict[str, dict]
    _hands: dict[str, object]

    if TYPE_CHECKING:

        def _require_sign_in(self) -> None: ...
        async def list_lessons(self, class_id: str) -> list[Lesson]: ...
        async def sync_roster(self, class_id: str) -> None: ...

    def _init_lifecycle(self) -> None:
        self._deleted_teams: dict[str, dict] = {}
        # The days of past Lessons that stay in the Teacher's calendar after their Class is gone.
        self._kept: list[date] = []

    # What a test does in Teams and inspects, as FakeGraph's.
    def delete_team(self, team_id: str) -> None:
        self._deleted_teams[team_id] = self._teams.pop(team_id)

    def undelete_team(self, team_id: str) -> None:
        self._teams[team_id] = self._deleted_teams.pop(team_id)

    async def calendar_dates(self, first: date, last: date) -> list[date]:
        days = list(self._kept)
        for class_id in self._classes:
            days += [x.start.date() for x in await self._own_lessons(class_id) if not x.cancelled]
        return sorted(d for d in days if first <= d <= last)

    async def _own_lessons(self, class_id: str) -> list[Lesson]:
        """The Class's Lessons that Classlop made, not the meetings made in Teams."""
        return [
            x for x in await self.list_lessons(class_id) if x.id.partition("@")[0] in self._events
        ]

    async def delete_class(self, class_id: str, name: str) -> None:
        self._require_sign_in()
        klass = self._classes[class_id]
        lifecycle.check_name(klass, name)
        await self._remove(klass, team=klass.state == "active")

    async def _remove(self, klass: Class, *, team: bool) -> None:
        now = self._clock()
        self._kept += [
            x.start.astimezone(WARSAW).date()
            for x in await self._own_lessons(klass.id)
            if x.start <= now and not x.cancelled
        ]
        for given in await self._of_class(klass.id):
            for name in lifecycle.schedule_names(given.id):
                await schedule.cancel(name)
            for submission in self._submissions[given.id].values():
                self._hands.pop(submission.id, None)
                await asyncio.to_thread(storage.delete_prefix, submissions.prefix(submission.id))
            self._drop_folders(self._assignment_dirs.pop(given.id, None))
            del self._assignments[given.id], self._submissions[given.id], self._pdfs[given.id]
        if team:
            self._deleted_teams[klass.team_id] = self._teams.pop(klass.team_id)
        for event_id in [i for i, e in self._events.items() if e["class_id"] == klass.id]:
            del self._events[event_id]
        for series in [s for s, p in self._placed.items() if p["class_id"] == klass.id]:
            del self._placed[series]
            self._seen = {k: v for k, v in self._seen.items() if v["series"] != series}
        self._links.pop(klass.id, None)
        for table in (self._classes, self._students, self._series, self._singles):
            del table[klass.id]

    async def _of_class(self, class_id: str) -> list[Assignment]:
        return [a for a in self._assignments.values() if a.class_id == class_id]

    def _drop_folders(self, path: str | None) -> None:
        if path is None:
            return
        self._folders = {f for f in self._folders if f != path and not f.startswith(path + "/")}
        self._drive = {k: v for k, v in self._drive.items() if not k.startswith(path + "/")}
        for user_id, shares in self._shares.items():
            self._shares[user_id] = [s for s in shares if not s.path.startswith(path + "/")]

    async def list_deleted_teams(self) -> list[Class]:
        return sorted(
            (c for c in self._classes.values() if c.state == "team_deleted"),
            key=lambda c: (c.team_deleted_at, c.name),
        )

    async def restore_team(self, class_id: str) -> Class:
        self._require_sign_in()
        team_id = self._classes[class_id].team_id
        if team_id in self._deleted_teams:
            self.undelete_team(team_id)
        await self.sync_roster(class_id)
        return self._classes[class_id]

    async def _team_found(self, class_id: str) -> bool:
        """Whether the Class's team exists in Teams, holding the Class if it does not and
        releasing it if it is back. A Class held for 30 days is deleted."""
        klass = self._classes[class_id]
        if klass.team_id in self._teams:
            if klass.state != "active":
                self._classes[class_id] = klass.model_copy(
                    update={"state": "active", "team_deleted_at": None}
                )
            return True
        if klass.state == "active":
            klass = klass.model_copy(
                update={"state": "team_deleted", "team_deleted_at": self._clock()}
            )
            self._classes[class_id] = klass
        if lifecycle.expired(klass, self._clock()):
            await self._remove(klass, team=False)
        return False
