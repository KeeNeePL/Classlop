"""FakeTeams: the `teams` interface in memory, for other areas' tests and TEAMS_BACKEND=fake.
Its seeding methods mirror FakeGraph's, which the contract suite relies on."""

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta

from ulid import ULID

from classlop.shared.jobs import SignInRequired
from classlop.shared.settings import get_settings
from classlop.teams import attendance
from classlop.teams.fake_giving import FakeGiving
from classlop.teams.fake_handins import FakeHandIns
from classlop.teams.fake_lifecycle import FakeLifecycle
from classlop.teams.lifecycle import writable
from classlop.teams.service import (
    AFTER,
    BEFORE,
    DEFAULT_LATENESS,
    WARSAW,
    attendance_due,
    calendar_window,
    next_weekday,
    now,
)
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


class FakeTeams(FakeGiving, FakeHandIns, FakeLifecycle):
    def __init__(self, clock: Callable[[], datetime] = now):
        self._clock = clock
        self._signed_in = True
        self._init_giving()
        self._init_handins()
        self._init_lifecycle()
        self._users: dict[str, tuple[str, str]] = {}
        self._teams: dict[str, dict] = {}
        self._classes: dict[str, Class] = {}
        self._students: dict[str, dict[str, Student]] = {}
        # Per Class: [event id, slot, first day, last day or None once replaced]
        self._series: dict[str, list[list]] = {}
        self._singles: dict[str, list[Lesson]] = {}
        self._events: dict[str, dict] = {}
        self._records: list[tuple[str, list[attendance.Session]]] = []
        self._attendees: dict[str, list[Attendee]] = {}
        self._fetched: dict[str, tuple[datetime, datetime]] = {}
        self._links: dict[str, dict[str, str]] = {}
        self._overrides: dict[str, dict[str, str]] = {}
        self._threshold = DEFAULT_LATENESS
        self._occurrences: dict[str, dict] = {}  # id@day -> subject, topic, cancelled
        # Teams meetings, what the calendar sync has seen of them, and where each belongs.
        self._meetings: dict[str, dict] = {}
        self._seen: dict[str, dict] = {}
        self._placed: dict[str, dict] = {}
        # Time changes made in Teams to Timetable and single Lessons, which Graph shows live.
        self._moved: dict[str, tuple[datetime, datetime]] = {}

    @staticmethod
    def _channel_id() -> str:
        return f"19:{uuid.uuid4().hex}@thread.tacv2"

    def add_user(self, name: str) -> str:
        user_id = str(uuid.uuid4())
        self._users[user_id] = (name, _upn(name))
        return user_id

    def add_team(self, name: str, *, owner: str | None = None, private: bool = False) -> str:
        team_id = str(uuid.uuid4())
        general = self._channel_id()
        self._teams[team_id] = {
            "name": name,
            "mine": owner is None,
            "members": {},
            "general": general,
            "channels": [general],
            "private": private,
        }
        return team_id

    def rename_team(self, team_id: str, name: str) -> None:
        self._teams[team_id]["name"] = name

    def team_name(self, team_id: str) -> str:
        return self._teams[team_id]["name"]

    def team_members(self, team_id: str) -> set[str]:
        return set(self._teams[team_id]["members"])

    def team_is_private(self, team_id: str) -> bool:
        return self._teams[team_id]["private"]

    def add_channel(self, team_id: str, name: str) -> str:
        channel = self._channel_id()
        self._teams[team_id]["channels"].append(channel)
        return channel

    def add_meeting(
        self,
        subject: str,
        start: datetime,
        end: datetime,
        *,
        attendees: list[str],
        channel: str | None = None,
        weekly_until: date | None = None,
    ) -> str:
        meeting_id = str(uuid.uuid4())
        self._meetings[meeting_id] = {
            "subject": subject,
            "start": start,
            "end": end,
            "attendees": {a.lower() for a in attendees},
            "channel": channel,
            "until": weekly_until,
            "cancelled": set(),
            "deleted": set(),
            "moved": {},
        }
        return meeting_id

    def reschedule(self, event_id: str, start: datetime, end: datetime) -> None:
        master, _, day = event_id.partition("@")
        if master not in self._meetings:
            self._moved[event_id] = (start, end)
        elif day:
            self._meetings[master]["moved"][day] = (start, end)
        else:
            self._meetings[master].update(start=start, end=end)

    def cancel(self, event_id: str) -> None:
        master, _, day = event_id.partition("@")
        if master in self._meetings:
            self._meetings[master]["cancelled"].add(day)
        elif event_id in self._events:
            self._events[event_id]["cancelled"] = True
        else:
            self._occurrences.setdefault(event_id, {})["cancelled"] = True

    def delete(self, event_id: str) -> None:
        master, _, day = event_id.partition("@")
        self._meetings[master]["deleted"].add(day)

    def _meeting_days(self, meeting_id: str) -> list[tuple[str, str, datetime, datetime]]:
        """(occurrence id, day, start, end) of a meeting; a single one has an empty day."""
        m = self._meetings[meeting_id]
        if not m["until"]:
            return [(meeting_id, "", m["start"], m["end"])]
        out, step = [], timedelta(days=7)
        start, end = m["start"], m["end"]
        while start.date() <= m["until"]:
            day = str(start.date())
            out.append((f"{meeting_id}@{day}", day, *m["moved"].get(day, (start, end))))
            start, end = start + step, end + step
        return out

    async def sync_calendar(self) -> None:
        self._require_sign_in()
        first, last = calendar_window(self._clock().astimezone(WARSAW).date())
        for meeting_id, m in self._meetings.items():
            for occurrence_id, day, start, end in self._meeting_days(meeting_id):
                if day in m["deleted"]:
                    self._seen.pop(occurrence_id, None)
                elif first <= start < last:
                    self._seen[occurrence_id] = {
                        "series": meeting_id,
                        "start": start,
                        "end": end,
                        "cancelled": day in m["cancelled"],
                    }
                    if meeting_id not in self._placed:
                        self._placed[meeting_id] = self._place(meeting_id)

    def _place(self, meeting_id: str) -> dict:
        m = self._meetings[meeting_id]
        placed = {"subject": m["subject"], "state": PENDING, "class_id": None, "candidates": []}
        rosters = {
            c: {s.upn.lower() for s in students.values() if not s.former_since}
            for c, students in self._students.items()
        }
        in_channel = [
            c
            for c, klass in self._classes.items()
            if m["channel"] in self._teams[klass.team_id]["channels"]
        ]
        exact = [c for c, r in rosters.items() if r and r == m["attendees"]]
        for found in (in_channel, exact):
            if len(found) == 1:
                return {**placed, "state": LESSON, "class_id": found[0]}
        placed["candidates"] = (
            in_channel or exact or [c for c, r in rosters.items() if r & m["attendees"]]
        )
        return placed

    async def list_calendar_questions(self) -> list[CalendarQuestion]:
        questions = [
            CalendarQuestion(
                id=series,
                subject=placed["subject"],
                start=min(r["start"] for r in self._seen.values() if r["series"] == series),
                candidates=placed["candidates"],
            )
            for series, placed in self._placed.items()
            if placed["state"] == PENDING
            and any(r["series"] == series for r in self._seen.values())
        ]
        return sorted(questions, key=lambda q: q.start)

    async def answer_calendar_question(self, question_id: str, answer: str) -> None:
        placed = self._placed.get(question_id)
        if placed is None or placed["state"] != PENDING:
            raise ValueError(f"no open question {question_id}")
        if answer in VERDICTS:
            placed["state"] = VERDICTS[answer]
        elif answer in placed["candidates"]:
            placed.update(state=LESSON, class_id=answer)
        else:
            raise ValueError(f"{answer!r} is not an answer to {question_id}")

    def add_member(
        self, team_id: str, name: str, *, owner: bool = False, user_id: str | None = None
    ) -> str:
        user_id = user_id or str(uuid.uuid4())
        self._teams[team_id]["members"][user_id] = (name, _upn(name), owner)
        return user_id

    def remove_member(self, team_id: str, user_id: str) -> None:
        del self._teams[team_id]["members"][user_id]

    def make_owner(self, team_id: str, user_id: str) -> None:
        name, upn, _ = self._teams[team_id]["members"][user_id]
        self._teams[team_id]["members"][user_id] = (name, upn, True)

    def lapse_sign_in(self) -> None:
        """From now on every call raises SignInRequired, as with a refresh token that fails."""
        self._signed_in = False

    def _require_sign_in(self) -> None:
        if not self._signed_in:
            raise SignInRequired

    async def list_owned_teams(self) -> list[Team]:
        self._require_sign_in()
        return [Team(id=i, name=t["name"]) for i, t in self._teams.items() if t["mine"]]

    async def link_team(self, team_id: str) -> Class:
        self._require_sign_in()
        if team_id not in {t.id for t in await self.list_owned_teams()}:
            raise NotOwner(team_id)
        if any(c.team_id == team_id for c in self._classes.values()):
            raise AlreadyLinked(team_id)
        return await self._link(team_id)

    async def _link(self, team_id: str) -> Class:
        klass = Class(
            id=str(ULID()),
            team_id=team_id,
            general_channel_id=self._teams[team_id]["general"],
            name=self._teams[team_id]["name"],
        )
        self._classes[klass.id] = klass
        self._students[klass.id] = {}
        self._series[klass.id], self._singles[klass.id] = [], []
        await self.sync_roster(klass.id)
        return klass

    async def get_class(self, class_id: str) -> Class:
        return self._classes[class_id]

    async def list_classes(self) -> list[Class]:
        return sorted(self._classes.values(), key=lambda c: c.name)

    async def list_students(self, class_id: str) -> list[Student]:
        return sorted(self._students[class_id].values(), key=lambda s: s.display_name)

    def event_of(self, event_id: str) -> tuple[str, set[str]]:
        """The subject and invitee addresses of a Lesson's event, as FakeGraph's."""
        event = self._events[event_id.split("@")[0]]
        subject = self._occurrences.get(event_id, {}).get("subject")
        return subject or event["subject"], set(event["invitees"])

    def _event(self, class_id: str, subject: str) -> str:
        event_id = str(uuid.uuid4())
        self._events[event_id] = {"subject": subject, "class_id": class_id, "invitees": set()}
        self._invite(event_id)
        return event_id

    def _invite(self, event_id: str) -> None:
        event = self._events[event_id]
        event["invitees"] = {
            s.upn for s in self._students[event["class_id"]].values() if not s.former_since
        }

    @writable
    async def add_timetable(self, class_id: str, slots: list[Slot], school_year_end: date) -> None:
        self._require_sign_in()
        if self._series[class_id]:
            raise TimetableExists(class_id)
        today = self._clock().astimezone(WARSAW).date()
        for slot in slots:
            self._start_series(class_id, slot, today)
        self._classes[class_id] = self._classes[class_id].model_copy(
            update={"school_year_end": school_year_end}
        )

    def _start_series(self, class_id: str, slot: Slot, from_day: date) -> None:
        first = next_weekday(from_day, slot.weekday)
        event_id = self._event(class_id, self._classes[class_id].name)
        self._series[class_id].append([event_id, slot, first, None])

    @writable
    async def change_slot(self, class_id: str, old: Slot, new: Slot, from_date: date) -> None:
        series = next((x for x in self._series[class_id] if x[1] == old and x[3] is None), None)
        if series is None:
            raise LookupError(old)
        if from_date <= series[2]:
            raise ValueError("a slot changes from after its first Lesson")
        series[3] = from_date - timedelta(days=1)
        self._start_series(class_id, new, from_date)

    @writable
    async def cancel_lessons(self, class_id: str, first: date, last: date) -> None:
        for lesson in await self.list_lessons(class_id):
            if first <= lesson.start.astimezone(WARSAW).date() <= last:
                if lesson.id in self._events:
                    self._events[lesson.id]["cancelled"] = True
                else:
                    self._occurrences.setdefault(lesson.id, {})["cancelled"] = True

    @writable
    async def set_lesson_topic(self, class_id: str, lesson_id: str, topic: str) -> Lesson:
        topic = topic.strip()
        if not topic:
            raise ValueError("a Lesson topic cannot be empty")
        lesson = next((x for x in await self.list_lessons(class_id) if x.id == lesson_id), None)
        if lesson is None:
            raise LookupError(lesson_id)
        subject = f"{self._classes[class_id].name}: {topic}"
        if lesson_id in self._events:
            self._events[lesson_id]["subject"] = subject
            self._singles[class_id] = [
                x.model_copy(update={"topic": topic}) if x.id == lesson_id else x
                for x in self._singles[class_id]
            ]
        else:
            self._occurrences.setdefault(lesson_id, {}).update(subject=subject, topic=topic)
        return lesson.model_copy(update={"topic": topic})

    @writable
    async def add_lesson(self, class_id: str, start: datetime, end: datetime, topic: str) -> Lesson:
        self._require_sign_in()
        topic = topic.strip()
        if not topic:
            raise ValueError("a Lesson needs a Lesson topic")
        event_id = self._event(class_id, f"{self._classes[class_id].name}: {topic}")
        lesson = Lesson(
            id=event_id,
            class_id=class_id,
            start=start,
            end=end,
            join_url=f"https://teams.example.org/l/{event_id}",
            topic=topic,
        )
        self._singles[class_id].append(lesson)
        return lesson

    async def list_lessons(self, class_id: str) -> list[Lesson]:
        lessons = [
            x.model_copy(update={"cancelled": self._events[x.id].get("cancelled", False)})
            for x in self._singles[class_id]
        ]
        for event_id, slot, day, last in self._series[class_id]:
            last = last or self._classes[class_id].school_year_end
            while day <= last:
                if day.weekday() == slot.weekday:
                    occurrence = self._occurrences.get(f"{event_id}@{day}", {})
                    lessons.append(
                        Lesson(
                            id=f"{event_id}@{day}",
                            class_id=class_id,
                            start=datetime.combine(day, slot.start, WARSAW),
                            end=datetime.combine(day, slot.end, WARSAW),
                            join_url=f"https://teams.example.org/l/{event_id}",
                            topic=occurrence.get("topic"),
                            cancelled=occurrence.get("cancelled", False),
                        )
                    )
                day += timedelta(days=1)
        for series, placed in self._placed.items():
            if placed["state"] == LESSON and placed["class_id"] == class_id:
                for occurrence_id, row in self._seen.items():
                    if row["series"] == series:
                        lessons.append(
                            Lesson(
                                id=occurrence_id,
                                class_id=class_id,
                                start=row["start"],
                                end=row["end"],
                                join_url=f"https://teams.example.org/l/{series}",
                                cancelled=row["cancelled"],
                            )
                        )
        shown = []
        for lesson in lessons:
            start, end = self._moved.get(lesson.id, (lesson.start, lesson.end))
            shown.append(lesson.model_copy(update={"start": start, "end": end}))
        return sorted(shown, key=lambda lesson: lesson.start)

    def attend(self, join_url: str, sessions: list[attendance.Session]) -> None:
        """A call record of the meeting at `join_url`, as FakeGraph's."""
        self._records.append((join_url, sessions))

    async def refresh_attendance(self, class_id: str, lesson_id: str) -> Attendance:
        lesson = next(x for x in await self.list_lessons(class_id) if x.id == lesson_id)
        if lesson.cancelled:
            return await self.get_attendance(class_id, lesson_id)
        found = [
            s
            for join_url, sessions in self._records
            if join_url == lesson.join_url
            and lesson.start - BEFORE <= min(s[2] for s in sessions) < lesson.end + AFTER
            for s in sessions
        ]
        self._attendees[lesson_id] = attendance.collect(found, get_settings().m365_teacher_oid)
        self._fetched[lesson_id] = (lesson.start, self._clock())
        return await self.get_attendance(class_id, lesson_id)

    async def get_attendance(self, class_id: str, lesson_id: str) -> Attendance:
        start, fetched_at = self._fetched.get(lesson_id, (None, None))
        return attendance.derive(
            lesson_id,
            await self.list_students(class_id),
            self._attendees.get(lesson_id, []),
            self._links.get(class_id, {}),
            self._overrides.get(lesson_id, {}),
            start,
            self._threshold,
            fetched_at,
        )

    async def fetch_due_attendance(self) -> int:
        fetched = 0
        for klass in await self.list_classes():
            for lesson in await self.list_lessons(klass.id):
                done = self._fetched.get(lesson.id, (None, None))[1]
                if not lesson.cancelled and attendance_due(lesson.end, done, self._clock()):
                    await self.refresh_attendance(klass.id, lesson.id)
                    fetched += 1
        return fetched

    @writable
    async def override_attendance(
        self, class_id: str, lesson_id: str, student_id: str, state: AttendanceState | None
    ) -> None:
        overrides = self._overrides.setdefault(lesson_id, {})
        if state is None:
            overrides.pop(student_id, None)
        else:
            overrides[student_id] = state

    @writable
    async def link_attendee(self, class_id: str, key: str, student_id: str) -> None:
        self._links.setdefault(class_id, {})[key] = student_id

    async def lateness_threshold(self) -> timedelta:
        return self._threshold

    async def set_lateness_threshold(self, threshold: timedelta) -> None:
        self._threshold = threshold

    async def sync_roster(self, class_id: str) -> None:
        self._require_sign_in()
        if not await self._team_found(class_id):
            return
        students = self._students[class_id]
        team = self._teams[self._classes[class_id].team_id]
        self._classes[class_id] = self._classes[class_id].model_copy(update={"name": team["name"]})
        members = team["members"]
        present = {u: m for u, m in members.items() if not m[2]}
        for user_id, (name, upn, _) in present.items():
            known = students.get(user_id)
            students[user_id] = Student(
                id=known.id if known else str(ULID()),
                class_id=class_id,
                user_id=user_id,
                display_name=name,
                upn=upn,
            )
        for user_id, student in students.items():
            if user_id not in present and student.former_since is None:
                students[user_id] = student.model_copy(update={"former_since": self._clock()})
        for event_id, event in self._events.items():
            if event["class_id"] == class_id:
                self._invite(event_id)

    async def search_users(self, query: str) -> list[Candidate]:
        return [
            Candidate(user_id=i, display_name=name, upn=upn)
            for i, (name, upn) in self._users.items()
            if any(word.startswith(query.lower()) for word in name.lower().split())
        ]

    async def create_class(self, name: str, student_user_ids: list[str]) -> Class:
        team_id = self.add_team(name, private=True)
        self.add_member(team_id, "Anna Nowak", owner=True)
        for user_id in student_user_ids:
            self.add_member(team_id, self._users[user_id][0], user_id=user_id)
        return await self._link(team_id)

    @writable
    async def add_student(self, class_id: str, user_id: str) -> Student:
        team_id = self._classes[class_id].team_id
        self.add_member(team_id, self._users[user_id][0], user_id=user_id)
        await self.sync_roster(class_id)
        return self._students[class_id][user_id]

    @writable
    async def remove_student(self, class_id: str, user_id: str) -> None:
        self.remove_member(self._classes[class_id].team_id, user_id)
        await self.sync_roster(class_id)

    @writable
    async def rename_class(self, class_id: str, name: str) -> Class:
        self.rename_team(self._classes[class_id].team_id, name)
        await self.sync_roster(class_id)
        return self._classes[class_id]


def _upn(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.org"


def demo() -> FakeTeams:
    """A tenant with invented content, so the dashboard has something to show."""
    fake = FakeTeams()
    team = fake.add_team("Klasa 2A matematyka")
    for name in ("Jan Kowalski", "Ewa Zielinska", "Piotr Wisniewski"):
        fake.add_member(team, name)
    fake.add_team("Klasa 3B matematyka")
    for name in ("Karolina Mazur", "Jan Kaminski"):
        fake.add_user(name)
    return fake
