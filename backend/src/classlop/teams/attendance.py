"""Attendance as pure functions over what Teams reported: the real area and FakeTeams share them."""

from collections.abc import Iterable
from datetime import datetime, timedelta

from classlop.teams.types import Attendance, AttendanceEntry, Attendee, Student, UnmatchedAttendee

Session = tuple[str | None, str, datetime, datetime]


def attendee_key(user_id: str | None, display_name: str) -> str:
    """Signed-in attendees are told apart by account, guests only by display name."""
    return user_id or "name:" + display_name


def collect(sessions: Iterable[Session], teacher_id: str) -> list[Attendee]:
    """One Attendee per person: sessions across every record merged, overlaps counted once."""
    spans: dict[str, list[tuple[datetime, datetime]]] = {}
    who: dict[str, tuple[str | None, str]] = {}
    for user_id, name, joined, left in sessions:
        if user_id == teacher_id:
            continue
        key = attendee_key(user_id, name)
        spans.setdefault(key, []).append((joined, left))
        who[key] = (user_id, name)
    out = []
    for key, items in spans.items():
        items.sort()
        seconds, edge = 0.0, items[0][0]
        for joined, left in items:
            seconds += max(0.0, (left - max(joined, edge)).total_seconds())
            edge = max(edge, left)
        out.append(
            Attendee(
                key=key,
                user_id=who[key][0],
                display_name=who[key][1],
                first_join=items[0][0],
                seconds=int(seconds),
            )
        )
    return out


def derive(
    lesson_id: str,
    students: list[Student],
    attendees: list[Attendee],
    links: dict[str, str],
    overrides: dict[str, str],
    start: datetime | None,
    threshold: timedelta,
    fetched_at: datetime | None,
) -> Attendance:
    """Each Student's state; `start` and `fetched_at` are None until the first fetch."""
    by_user = {s.user_id: s.id for s in students}
    joined: dict[str, list[Attendee]] = {}
    unmatched = []
    for a in attendees:
        student_id = by_user.get(a.user_id or "") or links.get(a.key)
        if student_id:
            joined.setdefault(student_id, []).append(a)
        else:
            unmatched.append(
                UnmatchedAttendee(key=a.key, display_name=a.display_name, minutes=a.seconds // 60)
            )
    entries = []
    for s in students:
        if s.former_since and s.id not in joined and s.id not in overrides:
            continue
        mine = joined.get(s.id, [])
        if s.id in overrides:
            state = overrides[s.id]
        elif fetched_at is None:
            state = None
        elif not mine:
            state = "absent"
        elif min(a.first_join for a in mine) > start + threshold:
            state = "late"
        else:
            state = "present"
        entries.append(
            AttendanceEntry(
                student_id=s.id,
                state=state,
                minutes=sum(a.seconds for a in mine) // 60,
                overridden=s.id in overrides,
            )
        )
    return Attendance(
        lesson_id=lesson_id, fetched_at=fetched_at, entries=entries, unmatched=unmatched
    )
