"""FakeTeams: the `teams` interface in memory, for other areas' tests and TEAMS_BACKEND=fake.
Its seeding methods mirror FakeGraph's, which the contract suite relies on."""

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta

from ulid import ULID

from classlop.teams.service import WARSAW, now, window
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


class FakeTeams:
    def __init__(self, clock: Callable[[], datetime] = now):
        self._clock = clock
        self._teams: dict[str, dict] = {}
        self._classes: dict[str, Class] = {}
        self._students: dict[str, dict[str, Student]] = {}
        self._series: dict[str, list[tuple[str, Slot, date]]] = {}
        self._singles: dict[str, list[Lesson]] = {}
        self._events: dict[str, dict] = {}
        # Teams meetings, what the calendar sync has seen of them, and where each belongs.
        self._meetings: dict[str, dict] = {}
        self._seen: dict[str, dict] = {}
        self._placed: dict[str, dict] = {}
        # Teams-side changes to Timetable and single Lessons, which Graph shows live.
        self._cancelled: set[str] = set()
        self._moved: dict[str, tuple[datetime, datetime]] = {}

    @staticmethod
    def _channel_id() -> str:
        return f"19:{uuid.uuid4().hex}@thread.tacv2"

    def add_team(self, name: str, *, owner: str | None = None) -> str:
        team_id = str(uuid.uuid4())
        general = self._channel_id()
        self._teams[team_id] = {
            "name": name,
            "mine": owner is None,
            "members": {},
            "general": general,
            "channels": [general],
        }
        return team_id

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
        if master not in self._meetings:
            self._cancelled.add(event_id)
        elif day:
            self._meetings[master]["cancelled"].add(day)
        else:
            del self._meetings[master]

    def _occurrences(self, meeting_id: str) -> list[tuple[str, datetime, datetime]]:
        m = self._meetings[meeting_id]
        if not m["until"]:
            return [(meeting_id, m["start"], m["end"])]
        out, step = [], timedelta(days=7)
        start, end = m["start"], m["end"]
        while start.date() <= m["until"]:
            day = str(start.date())
            if day not in m["cancelled"]:
                out.append((f"{meeting_id}@{day}", *m["moved"].get(day, (start, end))))
            start, end = start + step, end + step
        return out

    async def sync_calendar(self) -> None:
        first, last = window(self._clock().astimezone(WARSAW).date())
        alive = {o[0] for mid in self._meetings for o in self._occurrences(mid)}
        for occurrence_id, row in self._seen.items():
            row["cancelled"] = occurrence_id not in alive
        for meeting_id in self._meetings:
            for occurrence_id, start, end in self._occurrences(meeting_id):
                if first <= start < last:
                    self._seen[occurrence_id] = {
                        "series": meeting_id,
                        "start": start,
                        "end": end,
                        "cancelled": False,
                    }
                    if meeting_id not in self._placed:
                        self._placed[meeting_id] = self._place(meeting_id)

    def _place(self, meeting_id: str) -> dict:
        m = self._meetings[meeting_id]
        placed = {"subject": m["subject"], "state": "pending", "class_id": None, "candidates": []}
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
                return {**placed, "state": "lesson", "class_id": found[0]}
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
            if placed["state"] == "pending"
        ]
        return sorted(questions, key=lambda q: q.start)

    async def answer_calendar_question(self, question_id: str, answer: str) -> None:
        placed = self._placed.get(question_id)
        if placed is None or placed["state"] != "pending":
            raise ValueError(f"no open question {question_id}")
        if answer in ("keep", "hide"):
            placed["state"] = "kept" if answer == "keep" else "hidden"
        elif answer in placed["candidates"]:
            placed.update(state="lesson", class_id=answer)
        else:
            raise ValueError(f"{answer!r} is not an answer to {question_id}")

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
        for series, placed in self._placed.items():
            if placed["state"] == "lesson" and placed["class_id"] == class_id:
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
            cancelled = lesson.cancelled or lesson.id in self._cancelled
            shown.append(
                lesson.model_copy(update={"start": start, "end": end, "cancelled": cancelled})
            )
        return sorted(shown, key=lambda lesson: lesson.start)

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
