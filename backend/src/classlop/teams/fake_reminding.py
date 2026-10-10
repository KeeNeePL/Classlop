"""The Reminder in memory, for FakeTeams. The rules and the orchestration are Reminding's."""

import uuid
from typing import TYPE_CHECKING

from classlop.teams.fake_giving import Post
from classlop.teams.reminding import Reminding
from classlop.teams.types import Assignment, Class


class FakeReminding(Reminding):
    _posts: dict[str, list[Post]]
    _rejected: set[str]

    if TYPE_CHECKING:

        def _require_sign_in(self) -> None: ...
        def _save(self, assignment_id: str, **fields) -> Assignment: ...

    async def _store_reminder(self, assignment_id: str, on: bool) -> None:
        self._save(assignment_id, reminder_on=on)

    async def _announce(self, klass: Class, html: str) -> None:
        self._require_sign_in()
        if klass.team_id in self._rejected:
            raise RuntimeError("the post was refused")
        self._posts.setdefault(klass.team_id, []).append(Post(str(uuid.uuid4()), html, {}))
