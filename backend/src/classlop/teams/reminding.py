"""The Reminder: a one-time schedule a day before the due time that posts, in General, how many
Students have not handed in. GraphTeams and FakeTeams both inherit it; each supplies how the
flag is stored and how a post reaches General."""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from classlop.shared import schedule
from classlop.teams import reminders
from classlop.teams.graph import GraphClient, html_body
from classlop.teams.lifecycle import check_writable
from classlop.teams.types import Assignment, Class, Student, Submission


class Reminding:
    _clock: Callable[[], datetime]

    if TYPE_CHECKING:

        async def get_assignment(self, assignment_id: str) -> Assignment: ...
        async def get_class(self, class_id: str) -> Class: ...
        async def list_students(self, class_id: str) -> list[Student]: ...
        async def list_submissions(self, assignment_id: str) -> list[Submission]: ...
        async def _store_reminder(self, assignment_id: str, on: bool) -> None: ...
        async def _announce(self, klass: Class, html: str) -> None: ...

    async def set_reminder(self, assignment_id: str, on: bool) -> Assignment:
        given = await self.get_assignment(assignment_id)
        check_writable(await self.get_class(given.class_id))
        if given.state == "closed":
            raise ValueError("a closed Assignment has no Reminder")
        await self._store_reminder(assignment_id, on)
        await self.reschedule_reminder(assignment_id)
        return await self.get_assignment(assignment_id)

    async def reschedule_reminder(self, assignment_id: str) -> None:
        """Put the Reminder where the Assignment's times say, or take it away if there is to be
        none. Whatever changed them calls this; repeating it changes nothing."""
        given = await self.get_assignment(assignment_id)
        name, at = reminders.schedule_name(given.id), reminders.fires_at(given, self._clock())
        if at is None:
            await schedule.cancel(name)
        else:
            await schedule.at(name, at, "teams.remind_assignment", {"assignment_id": given.id})

    async def post_reminder(self, assignment_id: str) -> bool:
        """What the schedule runs. Whether it posted: it does not when the Reminder is off, the
        Assignment is not Open, the Class is read-only or all have handed in."""
        given = await self.get_assignment(assignment_id)
        if not reminders.is_due(given, self._clock()):
            return False
        klass = await self.get_class(given.class_id)
        if klass.state != "active":
            return False
        students = {s.id: s for s in await self.list_students(given.class_id)}
        pairs = [(s, students[s.student_id]) for s in await self.list_submissions(given.id)]
        if not (count := reminders.waiting(pairs)):
            return False
        await self._announce(klass, reminders.post_html(given, count))
        return True


class GraphReminding(Reminding):
    """Reminding through Graph; GraphTeams inherits it."""

    _graph: GraphClient

    if TYPE_CHECKING:

        async def _save_assignment(self, assignment_id: str, **fields) -> None: ...

    async def _store_reminder(self, assignment_id: str, on: bool) -> None:
        await self._save_assignment(assignment_id, reminder_on=on)

    async def _announce(self, klass: Class, html: str) -> None:
        await self._graph.send(
            "POST",
            f"/teams/{klass.team_id}/channels/{klass.general_channel_id}/messages",
            {"body": html_body(html)},
        )
