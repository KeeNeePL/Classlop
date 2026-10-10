"""Giving an Assignment as plain functions over what the Teacher decided: the real area and
FakeTeams share them, so the rules and the words Students read cannot drift."""

import re
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from classlop.teams.types import Assignment, AssignmentSpec, AssignmentType, Student

WARSAW = ZoneInfo("Europe/Warsaw")
LABELS: dict[AssignmentType, str] = {
    "homework": "Praca domowa",
    "quiz": "Kartkówka",
    "exam": "Sprawdzian",
}
# What OneDrive refuses in a name.
_FORBIDDEN = re.compile(r'[\\/:*?"<>|#%~\x00-\x1f]+')
RETRY_DELAY = 60
# Given, and not yet Closed: the states in which an Assignment still changes.
LIVE = ("scheduled", "open")


def check(spec: AssignmentSpec) -> None:
    if not spec.title.strip():
        raise ValueError("an Assignment needs a title")
    if not spec.item_ids:
        raise ValueError("an Assignment needs Items")
    if spec.close_at < spec.due_at:
        raise ValueError("an Assignment cannot close before it is due")


def check_time(when: datetime | None, now: datetime) -> None:
    if when is not None and when <= now:
        raise ValueError("an Assignment is scheduled for a time to come")


def recipients(students: list[Student], picked: list[str] | None) -> list[Student]:
    """The whole Class's current Students, or the picked ones, who must be in the Class."""
    current = [s for s in students if not s.former_since]
    if picked is None:
        return current
    chosen = [s for s in current if s.id in picked]
    if len(chosen) != len(set(picked)):
        raise ValueError("Students must be current Students of the Class")
    return chosen


def schedule_name(assignment_id: str) -> str:
    return f"teams.give:{assignment_id}"


def pdf_key(assignment_id: str) -> str:
    return f"teams/assignments/{assignment_id}/items.pdf"


def safe(name: str) -> str:
    """A name OneDrive accepts as a file or folder name."""
    return " ".join(_FORBIDDEN.sub(" ", name).split()).strip(".") or "Praca"


def local_time(moment: datetime) -> str:
    return moment.astimezone(WARSAW).strftime("%d.%m.%Y %H:%M")


def post_html(a: Assignment, attachment_id: str) -> str:
    """The post in General: the title, the due time and the Items PDF, no way to hand in."""
    return (
        f"<p><b>{escape(a.title)}</b> ({LABELS[a.type].lower()})</p>"
        f"<p>Termin oddania: {local_time(a.due_at)}</p>"
        f'<attachment id="{attachment_id}"></attachment>'
    )


def notice_html(a: Assignment, folder_url: str) -> str:
    """The «Nowa praca» chat message."""
    return (
        f"<p>«Nowa praca»: <b>{escape(a.title)}</b>. Termin oddania: {local_time(a.due_at)}.</p>"
        f'<p>Twój prywatny folder na zdjęcia pracy: <a href="{escape(folder_url)}">'
        "otwórz folder</a></p>"
        "<p>Link otwiera się w przeglądarce lub aplikacji OneDrive, nie w Teams.</p>"
    )
