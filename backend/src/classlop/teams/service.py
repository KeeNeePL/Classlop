import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from classlop.shared.db import sessions
from classlop.shared.settings import get_settings
from classlop.teams.graph import BASE, GraphClient
from classlop.teams.models import ClassRecord, LessonRecord, SlotRecord, StudentRecord
from classlop.teams.types import (
    AlreadyLinked,
    Candidate,
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
        return await self._link(team_id, team.name)

    async def _link(self, team_id: str, name: str) -> Class:
        channel = await self._graph.get(f"/teams/{team_id}/primaryChannel")
        row = ClassRecord(
            id=str(ULID()), team_id=team_id, general_channel_id=channel["id"], name=name
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
        rows = [
            await self._start_series(klass, slot, today, upns, school_year_end) for slot in slots
        ]
        async with sessions().begin() as session:
            session.add_all(rows)
            (await session.get_one(ClassRecord, class_id)).school_year_end = school_year_end

    async def _start_series(
        self, klass: Class, slot: Slot, from_day: date, upns: list[str], year_end: date
    ) -> SlotRecord:
        first = from_day + timedelta(days=(slot.weekday - from_day.weekday()) % 7)
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
                        "endDate": year_end.isoformat(),
                    },
                },
            },
        )
        return SlotRecord(
            id=str(ULID()),
            class_id=klass.id,
            event_id=event["id"],
            weekday=slot.weekday,
            start_time=slot.start,
            end_time=slot.end,
            first_on=first,
        )

    async def change_slot(self, class_id: str, old: Slot, new: Slot, from_date: date) -> None:
        klass = await self.get_class(class_id)
        async with sessions()() as session:
            current = await session.scalar(
                select(SlotRecord).where(
                    SlotRecord.class_id == class_id,
                    SlotRecord.last_on.is_(None),
                    SlotRecord.weekday == old.weekday,
                    SlotRecord.start_time == old.start,
                    SlotRecord.end_time == old.end,
                )
            )
        if current is None:
            raise LookupError(old)
        if from_date <= current.first_on:
            raise ValueError("a slot changes from after its first Lesson")
        last_on = from_date - timedelta(days=1)
        series = await self._graph.get(f"/me/events/{current.event_id}")
        recurrence = series["recurrence"]
        recurrence["range"]["endDate"] = last_on.isoformat()
        await self._graph.send(
            "PATCH", f"/me/events/{current.event_id}", {"recurrence": recurrence}
        )
        row = await self._start_series(
            klass, new, from_date, await self._invitees(class_id), klass.school_year_end
        )
        async with sessions().begin() as session:
            (await session.get_one(SlotRecord, current.id)).last_on = last_on
            session.add(row)

    async def cancel_lessons(self, class_id: str, first: date, last: date) -> None:
        for lesson in await self.list_lessons(class_id):
            if not lesson.cancelled and first <= lesson.start.astimezone(WARSAW).date() <= last:
                await self._graph.send("POST", f"/me/events/{lesson.id}/cancel", {})

    async def set_lesson_topic(self, class_id: str, lesson_id: str, topic: str) -> Lesson:
        topic = topic.strip()
        if not topic:
            raise ValueError("a Lesson topic cannot be empty")
        lesson = next((x for x in await self.list_lessons(class_id) if x.id == lesson_id), None)
        if lesson is None:
            raise LookupError(lesson_id)
        klass = await self.get_class(class_id)
        await self._graph.send(
            "PATCH", f"/me/events/{lesson_id}", {"subject": f"{klass.name}: {topic}"}
        )
        async with sessions().begin() as session:
            row = await session.get(LessonRecord, lesson_id)
            if row is None:
                session.add(
                    LessonRecord(id=lesson_id, class_id=class_id, topic=topic, single=False)
                )
            else:
                row.topic = topic
        return lesson.model_copy(update={"topic": topic})

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
            records = list(
                await session.scalars(select(LessonRecord).where(LessonRecord.class_id == class_id))
            )
        topics = {r.id: r.topic for r in records}
        lessons = []
        for slot in slots:
            last = slot.last_on or klass.school_year_end
            window = {
                "startDateTime": datetime.combine(slot.first_on, datetime.min.time(), WARSAW)
                .astimezone(UTC)
                .isoformat(),
                "endDateTime": datetime.combine(
                    last + timedelta(days=1), datetime.min.time(), WARSAW
                )
                .astimezone(UTC)
                .isoformat(),
            }
            for event in await self._graph.get_all(
                f"/me/events/{slot.event_id}/instances", **window
            ):
                lessons.append(self._lesson(class_id, event, topics.get(event["id"])))
        for record in records:
            if record.single:
                event = await self._graph.get(f"/me/events/{record.id}")
                lessons.append(self._lesson(class_id, event, record.topic))
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
            cancelled=event.get("isCancelled", False),
        )

    async def _invitees(self, class_id: str) -> list[str]:
        return [s.upn for s in await self.list_students(class_id) if not s.former_since]

    async def _invite_all(self, class_id: str) -> None:
        """Make the invitees of every event of the Class the current Students."""
        async with sessions()() as session:
            ids = list(
                await session.scalars(
                    select(SlotRecord.event_id).where(
                        SlotRecord.class_id == class_id, SlotRecord.last_on.is_(None)
                    )
                )
            ) + list(
                await session.scalars(
                    select(LessonRecord.id).where(
                        LessonRecord.class_id == class_id, LessonRecord.single
                    )
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
        name = (await self._graph.get(f"/teams/{klass.team_id}"))["displayName"]
        invited = await self._invitees(class_id)
        members = await self._graph.get_all(f"/teams/{klass.team_id}/members")
        present = {m["userId"]: m for m in members if "owner" not in m["roles"]}
        async with sessions().begin() as session:
            (await session.get_one(ClassRecord, class_id)).name = name
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

    async def search_users(self, query: str) -> list[Candidate]:
        users = await self._graph.get_all(
            "/users",
            **{"$search": f'"displayName:{query}"', "$select": "id,displayName,userPrincipalName"},
            headers={"ConsistencyLevel": "eventual"},
        )
        return [
            Candidate(user_id=u["id"], display_name=u["displayName"], upn=u["userPrincipalName"])
            for u in users
        ]

    async def create_class(self, name: str, student_user_ids: list[str]) -> Class:
        owner = get_settings().m365_teacher_oid
        response = await self._graph.request(
            "POST",
            "/teams",
            json={
                "template@odata.bind": f"{BASE}/teamsTemplates('standard')",
                "displayName": name,
                "visibility": "Private",
                "members": [_member(owner, "owner"), *(_member(u) for u in student_user_ids)],
            },
        )
        team_id = re.search(r"'([^']+)'", response.headers["Content-Location"])[1]
        operation = re.search(r"operations\('([^']+)'\)", response.headers["Location"])[1]
        await self._graph.wait_for(f"/teams/{team_id}/operations/{operation}")
        return await self._link(team_id, name)

    async def add_student(self, class_id: str, user_id: str) -> Student:
        klass = await self.get_class(class_id)
        await self._graph.request("POST", f"/teams/{klass.team_id}/members", json=_member(user_id))
        await self.sync_roster(class_id)
        return next(s for s in await self.list_students(class_id) if s.user_id == user_id)

    async def remove_student(self, class_id: str, user_id: str) -> None:
        klass = await self.get_class(class_id)
        members = await self._graph.get_all(f"/teams/{klass.team_id}/members")
        for member in members:
            if member["userId"] == user_id:
                await self._graph.request(
                    "DELETE", f"/teams/{klass.team_id}/members/{member['id']}"
                )
        await self.sync_roster(class_id)

    async def rename_class(self, class_id: str, name: str) -> Class:
        klass = await self.get_class(class_id)
        await self._graph.request("PATCH", f"/teams/{klass.team_id}", json={"displayName": name})
        async with sessions().begin() as session:
            row = await session.get_one(ClassRecord, class_id)
            row.name = name
        return klass.model_copy(update={"name": name})


def _member(user_id: str, *roles: str) -> dict:
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "roles": list(roles),
        "user@odata.bind": f"{BASE}/users('{user_id}')",
    }
