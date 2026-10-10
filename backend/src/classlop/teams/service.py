from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from urllib.parse import unquote

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from classlop.shared.db import sessions
from classlop.teams.graph import GraphClient, GraphError
from classlop.teams.models import (
    CalendarCursor,
    CalendarEventRecord,
    CalendarSeriesRecord,
    ClassRecord,
    LessonRecord,
    SlotRecord,
    StudentRecord,
)
from classlop.teams.types import (
    AlreadyLinked,
    CalendarQuestion,
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


def window(today: date) -> tuple[datetime, datetime]:
    """The calendar sync's span: 7 days back to 60 ahead, in Warsaw midnights."""
    first = datetime.combine(today - timedelta(days=7), datetime.min.time(), WARSAW)
    return first, first + timedelta(days=68)


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
        lessons: dict[str, Lesson] = {}
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
                lessons[event["id"]] = self._lesson(class_id, event, None)
        for single in singles:
            try:
                event = await self._graph.get(f"/me/events/{single.id}")
            except GraphError as error:
                if error.status != 404:
                    raise
                continue
            lessons[single.id] = self._lesson(class_id, event, single.topic)
        topics = {s.id: s.topic for s in singles}
        # Teams-made meetings, and what Teams has cancelled, are known from the calendar sync.
        async with sessions()() as session:
            rows = await session.scalars(
                select(CalendarEventRecord)
                .join(CalendarSeriesRecord)
                .where(CalendarSeriesRecord.class_id == class_id)
                .where(CalendarSeriesRecord.state == "lesson")
            )
            for row in rows:
                if row.id not in lessons:
                    lessons[row.id] = Lesson(
                        id=row.id,
                        class_id=class_id,
                        start=row.starts_at.astimezone(WARSAW),
                        end=row.ends_at.astimezone(WARSAW),
                        join_url=row.join_url,
                        topic=topics.get(row.series_id),
                        cancelled=row.cancelled,
                    )
        return sorted(lessons.values(), key=lambda lesson: lesson.start)

    async def sync_calendar(self) -> None:
        today = self._clock().astimezone(WARSAW).date()
        async with sessions()() as session:
            cursor = await session.get(CalendarCursor, "me")
            own = {
                key: class_id
                for key, class_id in [
                    *await session.execute(select(SlotRecord.event_id, SlotRecord.class_id)),
                    *await session.execute(select(LessonRecord.id, LessonRecord.class_id)),
                ]
            }
            known = set(await session.scalars(select(CalendarSeriesRecord.id)))
        if cursor and cursor.day == today:
            rows, link = await self._graph.get_delta(cursor.delta_link)
        else:
            first, last = window(today)
            rows, link = await self._graph.get_delta(
                "/me/calendarView/delta",
                startDateTime=first.astimezone(UTC).isoformat(),
                endDateTime=last.astimezone(UTC).isoformat(),
            )
        meetings = [r for r in rows if "@removed" in r or r.get("isOnlineMeeting")]
        fresh: dict[str, dict] = {}
        for row in meetings:
            key = row.get("seriesMasterId") or row["id"]
            if "@removed" not in row and key not in known:
                fresh.setdefault(key, row)
        placed = [await self._place(key, row, own) for key, row in fresh.items()]
        async with sessions().begin() as session:
            session.add_all(placed)
            await session.flush()
            for row in meetings:
                event = await session.get(CalendarEventRecord, row["id"])
                if "@removed" in row:
                    if event:
                        event.cancelled = True
                    continue
                if event is None:
                    event = CalendarEventRecord(
                        id=row["id"], series_id=row.get("seriesMasterId") or row["id"]
                    )
                    session.add(event)
                event.starts_at, event.ends_at = _utc(row["start"]), _utc(row["end"])
                event.cancelled = row.get("isCancelled", False)
                event.join_url = row["onlineMeeting"]["joinUrl"]
            await session.merge(CalendarCursor(id="me", delta_link=link, day=today))

    async def _place(self, key: str, row: dict, own: dict[str, str]) -> CalendarSeriesRecord:
        """Where a meeting new to the calendar belongs: its Class, or a question for the Teacher."""
        series = CalendarSeriesRecord(id=key, subject=row["subject"], class_id=None, candidates=[])
        if key in own:
            series.state, series.class_id = "lesson", own[key]
            return series
        invited = {a["emailAddress"]["address"].lower() for a in row.get("attendees", [])}
        rosters = {
            k.id: {s.upn.lower() for s in await self.list_students(k.id) if not s.former_since}
            for k in await self.list_classes()
        }
        url = unquote(row["onlineMeeting"]["joinUrl"])
        in_channel = []
        if "@thread.tacv2" in url:
            for klass in await self.list_classes():
                channels = await self._graph.get_all(f"/teams/{klass.team_id}/channels")
                if any(c["id"] in url for c in channels):
                    in_channel.append(klass.id)
        exact = [c for c, students in rosters.items() if students and students == invited]
        for found in (in_channel, exact):
            if len(found) == 1:
                series.state, series.class_id = "lesson", found[0]
                return series
        series.state = "pending"
        series.candidates = in_channel or exact or [c for c, s in rosters.items() if s & invited]
        return series

    async def list_calendar_questions(self) -> list[CalendarQuestion]:
        async with sessions()() as session:
            pending = await session.scalars(
                select(CalendarSeriesRecord).where(CalendarSeriesRecord.state == "pending")
            )
            questions = []
            for series in pending:
                first = await session.scalar(
                    select(CalendarEventRecord.starts_at)
                    .where(CalendarEventRecord.series_id == series.id)
                    .order_by(CalendarEventRecord.starts_at)
                    .limit(1)
                )
                assert first, "a pending series has an occurrence"
                questions.append(
                    CalendarQuestion(
                        id=series.id,
                        subject=series.subject,
                        start=first.astimezone(WARSAW),
                        candidates=series.candidates,
                    )
                )
        return sorted(questions, key=lambda q: q.start)

    async def answer_calendar_question(self, question_id: str, answer: str) -> None:
        async with sessions().begin() as session:
            series = await session.get(CalendarSeriesRecord, question_id)
            if series is None or series.state != "pending":
                raise ValueError(f"no open question {question_id}")
            if answer in ("keep", "hide"):
                series.state = "kept" if answer == "keep" else "hidden"
            elif answer in series.candidates:
                series.state, series.class_id = "lesson", answer
            else:
                raise ValueError(f"{answer!r} is not an answer to {question_id}")

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
