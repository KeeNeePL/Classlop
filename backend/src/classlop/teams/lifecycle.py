"""Deleting a Class, and a team deleted in Teams. The rules are plain functions shared with
FakeTeams; `Lifecycle` does them through Graph and GraphTeams inherits it."""

import asyncio
import functools
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Concatenate

from sqlalchemy import delete, select

from classlop.shared import schedule, storage
from classlop.shared.db import sessions
from classlop.teams import assignments, reminders, submissions
from classlop.teams.assignment_records import AssignmentRecord, SubmissionRecord
from classlop.teams.assignments import WARSAW
from classlop.teams.graph import GraphClient, GraphError
from classlop.teams.models import ClassRecord, LessonRecord, SlotRecord
from classlop.teams.types import Class, ClassReadOnly

# How long Microsoft keeps a deleted team restorable, and so how long its Class waits.
HOLD = timedelta(days=30)


def check_name(klass: Class, typed: str) -> None:
    if typed.strip() != klass.name:
        raise ValueError("type the Class name to delete it")


def check_writable(klass: Class) -> None:
    if klass.state != "active":
        raise ClassReadOnly(klass.id)


def writable[**P, R](
    method: Callable[Concatenate[Any, str, P], Awaitable[R]],
) -> Callable[Concatenate[Any, str, P], Awaitable[R]]:
    """For a method of GraphTeams or FakeTeams taking a Class id first: refuses a read-only
    Class."""

    @functools.wraps(method)
    async def guarded(self, class_id: str, *args: P.args, **kwargs: P.kwargs) -> R:
        check_writable(await self.get_class(class_id))
        return await method(self, class_id, *args, **kwargs)

    return guarded


def expired(klass: Class, at: datetime) -> bool:
    """A team deleted in Teams for 30 days is not coming back."""
    return klass.team_deleted_at is not None and at >= klass.team_deleted_at + HOLD


def schedule_names(assignment_id: str) -> list[str]:
    """Every schedule an Assignment can have, for the tickets that add them to list."""
    return [assignments.schedule_name(assignment_id), reminders.schedule_name(assignment_id)]


def _begins(event: dict) -> datetime:
    """When an event starts; the client asks Graph for UTC."""
    return datetime.fromisoformat(event["start"]["dateTime"][:26]).replace(tzinfo=UTC)


class Lifecycle:
    _graph: GraphClient
    _clock: Callable[[], datetime]

    if TYPE_CHECKING:

        async def get_class(self, class_id: str) -> Class: ...
        async def sync_roster(self, class_id: str) -> None: ...

    async def delete_class(self, class_id: str, name: str) -> None:
        klass = await self.get_class(class_id)
        check_name(klass, name)
        await self._remove(klass, team=klass.state == "active")

    async def list_deleted_teams(self) -> list[Class]:
        async with sessions()() as session:
            rows = await session.scalars(
                select(ClassRecord)
                .where(ClassRecord.state == "team_deleted")
                .order_by(ClassRecord.team_deleted_at, ClassRecord.name)
            )
            return [Class.model_validate(r, from_attributes=True) for r in rows]

    async def restore_team(self, class_id: str) -> Class:
        klass = await self.get_class(class_id)
        await self._graph.request("POST", f"/directory/deletedItems/{klass.team_id}/restore")
        await self.sync_roster(class_id)
        return await self.get_class(class_id)

    async def _team(self, klass: Class) -> dict | None:
        """The Class's team as Teams has it, or None if it is deleted: the Class is then held
        read-only from the time it was found, and deleted once it has waited 30 days. A team that
        is back releases the Class."""
        try:
            team = await self._graph.get(f"/teams/{klass.team_id}")
        except GraphError as error:
            if error.status != 404:
                raise
            if klass.state == "active":
                klass = klass.model_copy(
                    update={"state": "team_deleted", "team_deleted_at": self._clock()}
                )
                await self._save_state(klass)
            if expired(klass, self._clock()):
                await self._remove(klass, team=False)
            return None
        if klass.state != "active":
            await self._save_state(
                klass.model_copy(update={"state": "active", "team_deleted_at": None})
            )
        return team

    async def _save_state(self, klass: Class) -> None:
        async with sessions().begin() as session:
            row = await session.get_one(ClassRecord, klass.id)
            row.state, row.team_deleted_at = klass.state, klass.team_deleted_at

    async def _remove(self, klass: Class, *, team: bool) -> None:
        """Every step tolerates what is already gone, so a repeat finishes what one began; the
        records go last because they say what is left to remove."""
        async with sessions()() as session:
            rows = list(
                await session.scalars(
                    select(AssignmentRecord).where(AssignmentRecord.class_id == klass.id)
                )
            )
        for row in rows:
            for name in schedule_names(row.id):
                await schedule.cancel(name)
            if row.folder_id:
                await self._discard(f"/me/drive/items/{row.folder_id}")
            if row.pdf_key:
                await asyncio.to_thread(storage.delete, row.pdf_key)
            for submission_id in await self._submission_ids(row.id):
                await asyncio.to_thread(storage.delete_prefix, submissions.prefix(submission_id))
        await self._clear_calendar(klass.id)
        if team:
            await self._discard(f"/groups/{klass.team_id}")
        async with sessions().begin() as session:
            await session.execute(delete(ClassRecord).where(ClassRecord.id == klass.id))

    async def _submission_ids(self, assignment_id: str) -> list[str]:
        async with sessions()() as session:
            ids = await session.scalars(
                select(SubmissionRecord.id).where(SubmissionRecord.assignment_id == assignment_id)
            )
            return [str(i) for i in ids]

    async def _clear_calendar(self, class_id: str) -> None:
        """Remove the Lessons yet to begin: a Timetable series ends with its last Lesson begun,
        or goes whole if none has; a single Lesson goes if it has not begun."""
        now = self._clock()
        today = now.astimezone(WARSAW).date()
        async with sessions()() as session:
            slots = list(
                await session.scalars(select(SlotRecord).where(SlotRecord.class_id == class_id))
            )
            singles = list(
                await session.scalars(
                    select(LessonRecord.id).where(
                        LessonRecord.class_id == class_id, LessonRecord.single
                    )
                )
            )
        for slot in slots:
            begun = datetime.combine(today, slot.start_time, WARSAW) <= now
            last = today if begun else today - timedelta(days=1)
            if slot.last_on is not None and slot.last_on <= last:
                continue
            if last < slot.first_on:
                await self._discard(f"/me/events/{slot.event_id}")
                continue
            try:
                series = await self._graph.get(f"/me/events/{slot.event_id}")
            except GraphError as error:
                if error.status != 404:
                    raise
                continue
            series["recurrence"]["range"]["endDate"] = last.isoformat()
            await self._graph.send(
                "PATCH", f"/me/events/{slot.event_id}", {"recurrence": series["recurrence"]}
            )
        for event_id in singles:
            try:
                event = await self._graph.get(f"/me/events/{event_id}")
            except GraphError as error:
                if error.status != 404:
                    raise
                continue
            if _begins(event) > now:
                await self._discard(f"/me/events/{event_id}")

    async def _discard(self, url: str) -> None:
        try:
            await self._graph.request("DELETE", url)
        except GraphError as error:
            if error.status != 404:
                raise
