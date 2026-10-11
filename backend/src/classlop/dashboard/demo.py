"""Invented Notes for the demo school, written by `write_demo_notes` for the demo-school script."""

from sqlalchemy import delete

from classlop import teams
from classlop.dashboard.models import NoteRow
from classlop.shared.db import sessions

NOTES = [
    "Potrzebuje więcej czasu na zadania tekstowe.",
    "Chętnie tłumaczy rozwiązania kolegom.",
    "Często spóźnia się na lekcje, rozmowa z rodzicami w przyszłym tygodniu.",
    "Dobre wyniki, warto zaproponować zadania dodatkowe.",
]


async def write_demo_notes(students: dict[str, list[teams.Student]]) -> int:
    """A Note on a few Students of each Class (`students` by Class id); rewrites every Note."""
    written = 0
    async with sessions().begin() as session:
        await session.execute(delete(NoteRow))
        for class_id, found in students.items():
            for student, text in zip(found[::6], NOTES, strict=False):
                session.add(NoteRow(class_id=class_id, student_id=student.id, text=text))
                written += 1
    return written
