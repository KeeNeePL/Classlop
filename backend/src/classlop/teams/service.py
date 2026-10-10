import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from classlop.shared.db import sessions
from classlop.shared.settings import get_settings
from classlop.teams import attendance
from classlop.teams.changing import Changing
from classlop.teams.giving import Giving
from classlop.teams.graph import BASE, GraphClient, or_gone
from classlop.teams.handins import HandIns
from classlop.teams.lifecycle import Lifecycle, writable
from classlop.teams.models import (
    AttendeeRecord,
    CalendarCursor,
    CalendarEventRecord,
    CalendarSeriesRecord,
    ClassRecord,
    FetchRecord,
    LessonRecord,
    LinkRecord,
    OverrideRecord,
    SettingRecord,
    SlotRecord,
    StudentRecord,
)
from classlop.teams.reminding import GraphReminding
from classlop.teams.returning import Returning
from classlop.teams.types import (
    LESSON,
    PENDING,
    VERDICTS,
    AlreadyLinked,
    Attendance,
    AttendanceState,
    Attendee,
    CalendarQuestion,
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


LATENESS = "lateness_seconds"
DEFAULT_LATENESS = timedelta(minutes=5)
# Call records of a Lesson start within this window around it. A record appears about 27
# minutes after the meeting ends (ADR 0005), so the first fetch waits 45.
BEFORE, AFTER = timedelta(minutes=30), timedelta(hours=2)
FIRST_FETCH, SECOND_FETCH, GIVE_UP = timedelta(minutes=45), timedelta(hours=2), timedelta(days=3)


def now() -> datetime:
    return datetime.now(UTC)


def calendar_window(today: date) -> tuple[datetime, datetime]:
    """The calendar sync's span: 7 days back to 60 ahead, in Warsaw midnights."""
    first = datetime.combine(today - timedelta(days=7), datetime.min.time(), WARSAW)
    return first, first + timedelta(days=68)


def attendance_due(end: datetime, fetched_at: datetime | None, at: datetime) -> bool:
    """The first fetch at the end + 45 minutes, a second at + 2 hours, none after 3 days."""
    if at - end > GIVE_UP:
        return False
    if fetched_at is None:
        return at >= end + FIRST_FETCH
    return at >= end + SECOND_FETCH and fetched_at < end + SECOND_FETCH


def next_weekday(from_day: date, weekday: int) -> date:
    return from_day + timedelta(days=(weekday - from_day.weekday()) % 7)


def zulu(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(when: str) -> datetime:
    return datetime.fromisoformat(when)


def _class(row: ClassRecord) -> Class:
    return Class.model_validate(row, from_attributes=True)


def _utc(when: dict) -> datetime:
    """A Graph dateTimeTimeZone read as Warsaw time; the client asks for UTC."""
    return datetime.fromisoformat(when["dateTime"][:26]).replace(tzinfo=UTC).astimezone(WARSAW)


def local(when: datetime) -> dict:
    return {
        "dateTime": when.astimezone(WARSAW).replace(tzinfo=None).isoformat(),
        "timeZone": "Europe/Warsaw",
    }


def _attendees(upns: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": u}, "type": "required"} for u in upns]


class GraphTeams(Giving, HandIns, Returning, Lifecycle, GraphReminding, Changing):
    """The real area: Postgres records kept in step with the team through Graph."""

    def __init__(
        self,
        graph: GraphClient,
        clock: Callable[[], datetime] = now,
        records: GraphClient | None = None,
    ):
        """`records` reads call records with the app's own token (ADR 0005)."""
        self._graph, self._clock, self._records = graph, clock, records or graph

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

    @writable
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
        first = next_weekday(from_day, slot.weekday)
        event = await self._graph.send(
            "POST",
            "/me/events",
            {
                **self._event_body(klass.name, upns),
                "start": local(datetime.combine(first, slot.start, WARSAW)),
                "end": local(datetime.combine(first, slot.end, WARSAW)),
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

    @writable
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

    @writable
    async def cancel_lessons(self, class_id: str, first: date, last: date) -> None:
        for lesson in await self.list_lessons(class_id):
            if not lesson.cancelled and first <= lesson.start.astimezone(WARSAW).date() <= last:
                await self._graph.send("POST", f"/me/events/{lesson.id}/cancel", {})

    @writable
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

    @writable
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
                "start": local(start),
                "end": local(end),
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
        lessons: dict[str, Lesson] = {}
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
                lessons[event["id"]] = self._lesson(class_id, event, topics.get(event["id"]))
        for record in records:
            if not record.single:
                continue
            if event := await or_gone(self._graph.get(f"/me/events/{record.id}")):
                lessons[record.id] = self._lesson(class_id, event, record.topic)
        # Teams-made meetings, and what Teams has cancelled, are known from the calendar sync.
        async with sessions()() as session:
            rows = await session.scalars(
                select(CalendarEventRecord)
                .join(CalendarSeriesRecord)
                .where(CalendarSeriesRecord.class_id == class_id)
                .where(CalendarSeriesRecord.state == LESSON)
            )
            for row in rows:
                if row.id not in lessons:
                    lessons[row.id] = Lesson(
                        id=row.id,
                        class_id=class_id,
                        start=row.starts_at.astimezone(WARSAW),
                        end=row.ends_at.astimezone(WARSAW),
                        join_url=row.join_url,
                        topic=topics.get(row.id),
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
            first, last = calendar_window(today)
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
                        await session.delete(event)
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
            series.state, series.class_id = LESSON, own[key]
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
                series.state, series.class_id = LESSON, found[0]
                return series
        series.state = PENDING
        series.candidates = in_channel or exact or [c for c, s in rosters.items() if s & invited]
        return series

    async def list_calendar_questions(self) -> list[CalendarQuestion]:
        async with sessions()() as session:
            pending = await session.scalars(
                select(CalendarSeriesRecord).where(CalendarSeriesRecord.state == PENDING)
            )
            questions = []
            for series in pending:
                first = await session.scalar(
                    select(CalendarEventRecord.starts_at)
                    .where(CalendarEventRecord.series_id == series.id)
                    .order_by(CalendarEventRecord.starts_at)
                    .limit(1)
                )
                if first is None:
                    continue
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
            if series is None or series.state != PENDING:
                raise ValueError(f"no open question {question_id}")
            if answer in VERDICTS:
                series.state = VERDICTS[answer]
            elif answer in series.candidates:
                series.state, series.class_id = LESSON, answer
            else:
                raise ValueError(f"{answer!r} is not an answer to {question_id}")

    async def _lesson_of(self, class_id: str, lesson_id: str) -> Lesson:
        lesson = next((x for x in await self.list_lessons(class_id) if x.id == lesson_id), None)
        if lesson is None:
            raise ValueError(f"no Lesson {lesson_id} in class {class_id}")
        return lesson

    async def _sessions(self, lesson: Lesson) -> list[attendance.Session]:
        """Every session of every call record of the Lesson's meeting that began in its window."""
        since, until = zulu(lesson.start - BEFORE), zulu(lesson.end + AFTER)
        records = await self._records.get_all(
            "/communications/callRecords",
            **{"$filter": f"startDateTime ge {since} and startDateTime lt {until}"},
        )
        out: list[attendance.Session] = []
        for record in records:
            if record.get("joinWebUrl") != lesson.join_url:
                continue
            for s in await self._records.get_all(
                f"/communications/callRecords/{record['id']}/sessions"
            ):
                who = s["caller"]["identity"]
                person = who.get("user") or who["guest"]
                out.append(
                    (
                        person.get("id") if "user" in who else None,
                        person["displayName"],
                        _parse(s["startDateTime"]),
                        _parse(s["endDateTime"]),
                    )
                )
        return out

    async def refresh_attendance(self, class_id: str, lesson_id: str) -> Attendance:
        lesson = await self._lesson_of(class_id, lesson_id)
        if lesson.cancelled:
            return await self.get_attendance(class_id, lesson_id)
        found = attendance.collect(await self._sessions(lesson), get_settings().m365_teacher_oid)
        async with sessions().begin() as session:
            await session.execute(
                delete(AttendeeRecord).where(AttendeeRecord.lesson_id == lesson_id)
            )
            session.add_all(
                AttendeeRecord(lesson_id=lesson_id, class_id=class_id, **a.model_dump())
                for a in found
            )
            await session.merge(
                FetchRecord(
                    lesson_id=lesson_id,
                    class_id=class_id,
                    start=lesson.start,
                    fetched_at=self._clock(),
                )
            )
        return await self.get_attendance(class_id, lesson_id)

    async def get_attendance(self, class_id: str, lesson_id: str) -> Attendance:
        students = await self.list_students(class_id)
        threshold = await self.lateness_threshold()
        async with sessions()() as session:
            fetch = await session.get(FetchRecord, lesson_id)
            rows = await session.scalars(
                select(AttendeeRecord).where(AttendeeRecord.lesson_id == lesson_id)
            )
            found = [Attendee.model_validate(r, from_attributes=True) for r in rows]
            links = {
                r.key: r.student_id
                for r in await session.scalars(
                    select(LinkRecord).where(LinkRecord.class_id == class_id)
                )
            }
            overrides = {
                r.student_id: r.state
                for r in await session.scalars(
                    select(OverrideRecord).where(OverrideRecord.lesson_id == lesson_id)
                )
            }
        return attendance.derive(
            lesson_id,
            students,
            found,
            links,
            overrides,
            fetch and fetch.start,
            threshold,
            fetch and fetch.fetched_at,
        )

    async def fetch_due_attendance(self) -> int:
        now = self._clock()
        fetched = 0
        for klass in await self.list_classes():
            async with sessions()() as session:
                done = {
                    r.lesson_id: r.fetched_at
                    for r in await session.scalars(
                        select(FetchRecord).where(FetchRecord.class_id == klass.id)
                    )
                }
            for lesson in await self.list_lessons(klass.id):
                if not lesson.cancelled and attendance_due(lesson.end, done.get(lesson.id), now):
                    await self.refresh_attendance(klass.id, lesson.id)
                    fetched += 1
        return fetched

    @writable
    async def override_attendance(
        self, class_id: str, lesson_id: str, student_id: str, state: AttendanceState | None
    ) -> None:
        async with sessions().begin() as session:
            if state is None:
                await session.execute(
                    delete(OverrideRecord).where(
                        OverrideRecord.lesson_id == lesson_id,
                        OverrideRecord.student_id == student_id,
                    )
                )
            else:
                await session.merge(
                    OverrideRecord(
                        lesson_id=lesson_id, student_id=student_id, class_id=class_id, state=state
                    )
                )

    @writable
    async def link_attendee(self, class_id: str, key: str, student_id: str) -> None:
        async with sessions().begin() as session:
            await session.merge(LinkRecord(class_id=class_id, key=key, student_id=student_id))

    async def lateness_threshold(self) -> timedelta:
        async with sessions()() as session:
            row = await session.get(SettingRecord, LATENESS)
        return timedelta(seconds=int(row.value)) if row else DEFAULT_LATENESS

    async def set_lateness_threshold(self, threshold: timedelta) -> None:
        async with sessions().begin() as session:
            await session.merge(
                SettingRecord(key=LATENESS, value=str(int(threshold.total_seconds())))
            )

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
        team = await self._team(klass)
        if team is None:
            return
        name = team["displayName"]
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
        await self._catch_up(class_id)

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

    @writable
    async def add_student(self, class_id: str, user_id: str) -> Student:
        klass = await self.get_class(class_id)
        await self._graph.request("POST", f"/teams/{klass.team_id}/members", json=_member(user_id))
        await self.sync_roster(class_id)
        return next(s for s in await self.list_students(class_id) if s.user_id == user_id)

    @writable
    async def remove_student(self, class_id: str, user_id: str) -> None:
        klass = await self.get_class(class_id)
        members = await self._graph.get_all(f"/teams/{klass.team_id}/members")
        for member in members:
            if member["userId"] == user_id:
                await self._graph.request(
                    "DELETE", f"/teams/{klass.team_id}/members/{member['id']}"
                )
        await self.sync_roster(class_id)

    @writable
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
