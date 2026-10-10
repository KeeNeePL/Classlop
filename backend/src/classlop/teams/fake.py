"""FakeTeams: the `teams` interface in memory, for other areas' tests and TEAMS_BACKEND=fake.
Its seeding methods mirror FakeGraph's, which the contract suite relies on."""

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta

from ulid import ULID

from classlop.teams.service import WARSAW, now
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


class FakeTeams:
    def __init__(self, clock: Callable[[], datetime] = now):
        self._clock = clock
        self._users: dict[str, tuple[str, str]] = {}
        self._teams: dict[str, dict] = {}
        self._classes: dict[str, Class] = {}
        self._students: dict[str, dict[str, Student]] = {}
        self._series: dict[str, list[tuple[str, Slot, date]]] = {}
        self._singles: dict[str, list[Lesson]] = {}
        self._events: dict[str, dict] = {}

    def add_user(self, name: str) -> str:
        user_id = str(uuid.uuid4())
        self._users[user_id] = (name, _upn(name))
        return user_id

    def add_team(self, name: str, *, owner: str | None = None, private: bool = False) -> str:
        team_id = str(uuid.uuid4())
        self._teams[team_id] = {
            "name": name,
            "mine": owner is None,
            "members": {},
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

    async def list_owned_teams(self) -> list[Team]:
        return [Team(id=i, name=t["name"]) for i, t in self._teams.items() if t["mine"]]

    async def link_team(self, team_id: str) -> Class:
        if team_id not in {t.id for t in await self.list_owned_teams()}:
            raise NotOwner(team_id)
        if any(c.team_id == team_id for c in self._classes.values()):
            raise AlreadyLinked(team_id)
        return await self._link(team_id)

    async def _link(self, team_id: str) -> Class:
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

    async def sync_roster(self, class_id: str) -> None:
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

    async def add_student(self, class_id: str, user_id: str) -> Student:
        team_id = self._classes[class_id].team_id
        self.add_member(team_id, self._users[user_id][0], user_id=user_id)
        await self.sync_roster(class_id)
        return self._students[class_id][user_id]

    async def remove_student(self, class_id: str, user_id: str) -> None:
        self.remove_member(self._classes[class_id].team_id, user_id)
        await self.sync_roster(class_id)

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
