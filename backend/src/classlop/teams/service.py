from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from classlop.shared.db import sessions
from classlop.teams.graph import GraphClient
from classlop.teams.models import ClassRecord, LessonRecord, SlotRecord, StudentRecord
from classlop.teams.types import (
    AlreadyLinked,
    Class,
    Lesson,
    NotOwner,
    Slot,
    Student,
    Team,
    TimetableExists,
)

WARSAW = ZoneInfo("Europe/Warsaw")
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def now() -> datetime:
    return datetime.now(UTC)


def _class(row: ClassRecord) -> Class:
    return Class.model_validate(row, from_attributes=True)


def _utc(when: dict) -> datetime:
    """A Graph dateTimeTimeZone read as Warsaw time; the client asks for UTC."""
    return datetime.fromisoformat(when["dateTime"][:26]).replace(tzinfo=UTC).astimezone(WARSAW)


def _local(when: datetime) -> dict:
    return {
        "dateTime": when.astimezone(WARSAW).replace(tzinfo=None).isoformat(),
        "timeZone": "Europe/Warsaw",
    }


def _attendees(upns: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": u}, "type": "required"} for u in upns]


class GraphTeams:
    """The real area: Postgres records kept in step with the team through Graph."""

    def __init__(self, graph: GraphClient, clock: Callable[[], datetime] = now):
        self._graph, self._clock = graph, clock

    async def list_owned_teams(self) -> list[Team]:
        groups = await self._graph.get_all("/me/ownedObjects/microsoft.graph.group")
        return [
            Team(id=g["id"], name=g["displayName"])
            for g in groups
            if "Team" in g.get("resourceProvisioningOptions", [])
        ]

    async def link_team(self, team_id: str) -> Class:
        team = next((t for t in await self.list_owned_teams() if t.id == team_id), None)
        if team is None:
            raise NotOwner(team_id)
        channel = await self._graph.get(f"/teams/{team_id}/primaryChannel")
        row = ClassRecord(
            id=str(ULID()),
            team_id=team_id,
            general_channel_id=channel["id"],
            name=team.name,
        )
        try:
            async with sessions().begin() as session:
                session.add(row)
        except IntegrityError:
            raise AlreadyLinked(team_id) from None
        await self.sync_roster(row.id)
        return _class(row)

    async def add_timetable(self, class_id: str, slots: list[Slot], school_year_end: date) -> None:
        klass = await self.get_class(class_id)
        async with sessions()() as session:
            if await session.scalar(select(SlotRecord.id).where(SlotRecord.class_id == class_id)):
                raise TimetableExists(class_id)
        today = self._clock().astimezone(WARSAW).date()
        upns = await self._invitees(class_id)
        rows = []
        for slot in slots:
            first = today + timedelta(days=(slot.weekday - today.weekday()) % 7)
            event = await self._graph.send(
                "POST",
                "/me/events",
                {
                    **self._event_body(klass.name, upns),
                    "start": _local(datetime.combine(first, slot.start, WARSAW)),
                    "end": _local(datetime.combine(first, slot.end, WARSAW)),
                    "recurrence": {
                        "pattern": {
                            "type": "weekly",
                            "interval": 1,
                            "daysOfWeek": [_DAYS[slot.weekday]],
                        },
                        "range": {
                            "type": "endDate",
                            "startDate": first.isoformat(),
                            "endDate": school_year_end.isoformat(),
                        },
                    },
                },
            )
            rows.append(
                SlotRecord(
                    id=str(ULID()),
                    class_id=class_id,
                    event_id=event["id"],
                    weekday=slot.weekday,
                    start_time=slot.start,
                    end_time=slot.end,
                    first_on=first,
                )
            )
        async with sessions().begin() as session:
            session.add_all(rows)
            (await session.get_one(ClassRecord, class_id)).school_year_end = school_year_end

    async def add_lesson(self, class_id: str, start: datetime, end: datetime, topic: str) -> Lesson:
        topic = topic.strip()
        if not topic:
            raise ValueError("a Lesson needs a Lesson topic")
        klass = await self.get_class(class_id)
        event = await self._graph.send(
            "POST",
            "/me/events",
            {
                **self._event_body(f"{klass.name}: {topic}", await self._invitees(class_id)),
                "start": _local(start),
                "end": _local(end),
            },
        )
        async with sessions().begin() as session:
            session.add(LessonRecord(id=event["id"], class_id=class_id, topic=topic))
        return self._lesson(class_id, event, topic)

    async def list_lessons(self, class_id: str) -> list[Lesson]:
        klass = await self.get_class(class_id)
        async with sessions()() as session:
            slots = list(
                await session.scalars(select(SlotRecord).where(SlotRecord.class_id == class_id))
            )
            singles = list(
                await session.scalars(select(LessonRecord).where(LessonRecord.class_id == class_id))
            )
        lessons = []
        for slot in slots:
            window = {
                "startDateTime": datetime.combine(slot.first_on, datetime.min.time(), WARSAW)
                .astimezone(UTC)
                .isoformat(),
                "endDateTime": datetime.combine(
                    klass.school_year_end + timedelta(days=1), datetime.min.time(), WARSAW
                )
                .astimezone(UTC)
                .isoformat(),
            }
            for event in await self._graph.get_all(
                f"/me/events/{slot.event_id}/instances", **window
            ):
                lessons.append(self._lesson(class_id, event, None))
        for single in singles:
            event = await self._graph.get(f"/me/events/{single.id}")
            lessons.append(self._lesson(class_id, event, single.topic))
        return sorted(lessons, key=lambda lesson: lesson.start)

    @staticmethod
    def _event_body(subject: str, upns: list[str]) -> dict:
        return {
            "subject": subject,
            "isOnlineMeeting": True,
            "onlineMeetingProvider": "teamsForBusiness",
            "attendees": _attendees(upns),
        }

    @staticmethod
    def _lesson(class_id: str, event: dict, topic: str | None) -> Lesson:
        return Lesson(
            id=event["id"],
            class_id=class_id,
            start=_utc(event["start"]),
            end=_utc(event["end"]),
            join_url=event["onlineMeeting"]["joinUrl"],
            topic=topic,
        )

    async def _invitees(self, class_id: str) -> list[str]:
        return [s.upn for s in await self.list_students(class_id) if not s.former_since]

    async def _invite_all(self, class_id: str) -> None:
        """Make the invitees of every event of the Class the current Students."""
        async with sessions()() as session:
            ids = list(
                await session.scalars(
                    select(SlotRecord.event_id).where(SlotRecord.class_id == class_id)
                )
            ) + list(
                await session.scalars(
                    select(LessonRecord.id).where(LessonRecord.class_id == class_id)
                )
            )
        attendees = _attendees(await self._invitees(class_id))
        for event_id in ids:
            await self._graph.send("PATCH", f"/me/events/{event_id}", {"attendees": attendees})

    async def get_class(self, class_id: str) -> Class:
        async with sessions()() as session:
            return _class(await session.get_one(ClassRecord, class_id))

    async def list_classes(self) -> list[Class]:
        async with sessions()() as session:
            rows = await session.scalars(select(ClassRecord).order_by(ClassRecord.name))
            return [_class(r) for r in rows]

    async def list_students(self, class_id: str) -> list[Student]:
        async with sessions()() as session:
            rows = await session.scalars(
                select(StudentRecord)
                .where(StudentRecord.class_id == class_id)
                .order_by(StudentRecord.display_name)
            )
            return [Student.model_validate(r, from_attributes=True) for r in rows]

    async def sync_roster(self, class_id: str) -> None:
        """Members who are not owners are Students; anyone else becomes a Former student."""
        klass = await self.get_class(class_id)
        invited = await self._invitees(class_id)
        members = await self._graph.get_all(f"/teams/{klass.team_id}/members")
        present = {m["userId"]: m for m in members if "owner" not in m["roles"]}
        async with sessions().begin() as session:
            known = {
                r.user_id: r
                for r in await session.scalars(
                    select(StudentRecord).where(StudentRecord.class_id == class_id)
                )
            }
            for user_id, member in present.items():
                row = known.get(user_id)
                if row is None:
                    row = StudentRecord(id=str(ULID()), class_id=class_id, user_id=user_id)
                    session.add(row)
                row.display_name = member["displayName"]
                row.upn = member.get("email") or ""
                row.former_since = None
            for user_id, row in known.items():
                if user_id not in present and row.former_since is None:
                    row.former_since = self._clock()
        if sorted(invited) != sorted(await self._invitees(class_id)):
            await self._invite_all(class_id)
