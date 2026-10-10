"""FakeTeams: the `teams` interface in memory, for other areas' tests and TEAMS_BACKEND=fake.
Its seeding methods mirror FakeGraph's, which the contract suite relies on."""

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta

from ulid import ULID

from classlop.teams.service import WARSAW, now
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


class FakeTeams:
    def __init__(self, clock: Callable[[], datetime] = now):
        self._clock = clock
        self._teams: dict[str, dict] = {}
        self._classes: dict[str, Class] = {}
        self._students: dict[str, dict[str, Student]] = {}
        # Per Class: [event id, slot, first day, last day or None once replaced]
        self._series: dict[str, list[list]] = {}
        self._singles: dict[str, list[Lesson]] = {}
        self._events: dict[str, dict] = {}
        self._occurrences: dict[str, dict] = {}  # id@day -> subject, topic, cancelled

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

    async def add_timetable(self, class_id: str, slots: list[Slot], school_year_end: date) -> None:
        if self._series[class_id]:
            raise TimetableExists(class_id)
        today = self._clock().astimezone(WARSAW).date()
        for slot in slots:
            self._start_series(class_id, slot, today)
        self._classes[class_id] = self._classes[class_id].model_copy(
            update={"school_year_end": school_year_end}
        )

    def _start_series(self, class_id: str, slot: Slot, from_day: date) -> None:
        first = from_day + timedelta(days=(slot.weekday - from_day.weekday()) % 7)
        event_id = self._event(class_id, self._classes[class_id].name)
        self._series[class_id].append([event_id, slot, first, None])

    async def change_slot(self, class_id: str, old: Slot, new: Slot, from_date: date) -> None:
        series = next((x for x in self._series[class_id] if x[1] == old and x[3] is None), None)
        if series is None:
            raise LookupError(old)
        if from_date <= series[2]:
            raise ValueError("a slot changes from after its first Lesson")
        series[3] = from_date - timedelta(days=1)
        self._start_series(class_id, new, from_date)

    async def cancel_lessons(self, class_id: str, first: date, last: date) -> None:
        for lesson in await self.list_lessons(class_id):
            if first <= lesson.start.astimezone(WARSAW).date() <= last:
                if lesson.id in self._events:
                    self._events[lesson.id]["cancelled"] = True
                else:
                    self._occurrences.setdefault(lesson.id, {})["cancelled"] = True

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
        return sorted(lessons, key=lambda lesson: lesson.start)

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
