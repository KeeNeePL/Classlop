"""FakeTeams: the `teams` interface in memory, for other areas' tests and TEAMS_BACKEND=fake.
Its seeding methods mirror FakeGraph's, which the contract suite relies on."""

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta

from ulid import ULID

from classlop.shared.settings import get_settings
from classlop.teams import attendance
from classlop.teams.service import (
    AFTER,
    BEFORE,
    DEFAULT_LATENESS,
    WARSAW,
    attendance_due,
    now,
)
from classlop.teams.types import (
    AlreadyLinked,
    Attendance,
    AttendanceState,
    Attendee,
    Class,
    Lesson,
    NotOwner,
    Slot,
    Student,
    Team,
    TimetableExists,
)


class FakeTeams:
    def __init__(self, clock: Callable[[], datetime] = now):
        self._clock = clock
        self._teams: dict[str, dict] = {}
        self._classes: dict[str, Class] = {}
        self._students: dict[str, dict[str, Student]] = {}
        self._series: dict[str, list[tuple[str, Slot, date]]] = {}
        self._singles: dict[str, list[Lesson]] = {}
        self._events: dict[str, dict] = {}
        self._records: list[tuple[str, list[attendance.Session]]] = []
        self._attendees: dict[str, list[Attendee]] = {}
        self._fetched: dict[str, tuple[datetime, datetime]] = {}
        self._links: dict[str, dict[str, str]] = {}
        self._overrides: dict[str, dict[str, str]] = {}
        self._threshold = DEFAULT_LATENESS

    def add_team(self, name: str, *, owner: str | None = None) -> str:
        team_id = str(uuid.uuid4())
        self._teams[team_id] = {"name": name, "mine": owner is None, "members": {}}
        return team_id

    def add_member(
        self, team_id: str, name: str, *, owner: bool = False, user_id: str | None = None
    ) -> str:
        user_id = user_id or str(uuid.uuid4())
        upn = name.lower().replace(" ", ".") + "@example.org"
        self._teams[team_id]["members"][user_id] = (name, upn, owner)
        return user_id

    def remove_member(self, team_id: str, user_id: str) -> None:
        del self._teams[team_id]["members"][user_id]

    def make_owner(self, team_id: str, user_id: str) -> None:
        name, upn, _ = self._teams[team_id]["members"][user_id]
        self._teams[team_id]["members"][user_id] = (name, upn, True)

    async def list_owned_teams(self) -> list[Team]:
        return [Team(id=i, name=t["name"]) for i, t in self._teams.items() if t["mine"]]

    async def link_team(self, team_id: str) -> Class:
        if team_id not in {t.id for t in await self.list_owned_teams()}:
            raise NotOwner(team_id)
        if any(c.team_id == team_id for c in self._classes.values()):
            raise AlreadyLinked(team_id)
        klass = Class(
            id=str(ULID()),
            team_id=team_id,
            general_channel_id=str(uuid.uuid4()),
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
        return event["subject"], set(event["invitees"])

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

    async def add_timetable(self, class_id: str, slots: list[Slot], school_year_end: date) -> None:
        if self._series[class_id]:
            raise TimetableExists(class_id)
        today = self._clock().astimezone(WARSAW).date()
        for slot in slots:
            first = today + timedelta(days=(slot.weekday - today.weekday()) % 7)
            event_id = self._event(class_id, self._classes[class_id].name)
            self._series[class_id].append((event_id, slot, first))
        self._classes[class_id] = self._classes[class_id].model_copy(
            update={"school_year_end": school_year_end}
        )

    async def add_lesson(self, class_id: str, start: datetime, end: datetime, topic: str) -> Lesson:
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
        lessons = list(self._singles[class_id])
        last = self._classes[class_id].school_year_end
        for event_id, slot, day in self._series[class_id]:
            while day <= last:
                if day.weekday() == slot.weekday:
                    lessons.append(
                        Lesson(
                            id=f"{event_id}@{day}",
                            class_id=class_id,
                            start=datetime.combine(day, slot.start, WARSAW),
                            end=datetime.combine(day, slot.end, WARSAW),
                            join_url=f"https://teams.example.org/l/{event_id}",
                        )
                    )
                day += timedelta(days=1)
        return sorted(lessons, key=lambda lesson: lesson.start)

    def attend(self, join_url: str, sessions: list[attendance.Session]) -> None:
        """A call record of the meeting at `join_url`, as FakeGraph's."""
        self._records.append((join_url, sessions))

    async def refresh_attendance(self, class_id: str, lesson_id: str) -> Attendance:
        lesson = next(x for x in await self.list_lessons(class_id) if x.id == lesson_id)
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
                if attendance_due(lesson.end, done, self._clock()):
                    await self.refresh_attendance(klass.id, lesson.id)
                    fetched += 1
        return fetched

    async def override_attendance(
        self, class_id: str, lesson_id: str, student_id: str, state: AttendanceState | None
    ) -> None:
        overrides = self._overrides.setdefault(lesson_id, {})
        if state is None:
            overrides.pop(student_id, None)
        else:
            overrides[student_id] = state

    async def link_attendee(self, class_id: str, key: str, student_id: str) -> None:
        self._links.setdefault(class_id, {})[key] = student_id

    async def lateness_threshold(self) -> timedelta:
        return self._threshold

    async def set_lateness_threshold(self, threshold: timedelta) -> None:
        self._threshold = threshold

    async def sync_roster(self, class_id: str) -> None:
        students = self._students[class_id]
        members = self._teams[self._classes[class_id].team_id]["members"]
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


def demo() -> FakeTeams:
    """A tenant with invented content, so the dashboard has something to show."""
    fake = FakeTeams()
    team = fake.add_team("Klasa 2A matematyka")
    for name in ("Jan Kowalski", "Ewa Zielinska", "Piotr Wisniewski"):
        fake.add_member(team, name)
    fake.add_team("Klasa 3B matematyka")
    return fake
