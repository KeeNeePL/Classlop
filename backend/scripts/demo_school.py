"""Fills the local database with an invented school for development and the demo: three Classes of
25 Students with Lessons, Attendance and graded Assignments. Rerunning starts from a clean slate.

    uv run python scripts/demo_school.py

Needs the compose stand-ins (`docker compose up -d`); a running worker then indexes the Items.
Every name and Item is invented.
"""

import asyncio
from datetime import UTC, datetime

from classlop.dashboard.demo import write_demo_notes
from classlop.grading.demo import write_demo_grades
from classlop.items.demo import write_demo_items
from classlop.shared.migrate import migrate
from classlop.teams.demo import write_demo_teams
from classlop.teams.types import Student


async def fill(now: datetime) -> None:
    item_ids = await write_demo_items()
    assignments, submissions, students = await write_demo_teams(item_ids, now)
    await write_demo_grades(assignments, submissions)
    classes: dict[str, list[Student]] = {}
    for student in students:
        classes.setdefault(student.class_id, []).append(student)
    await write_demo_notes(classes)


async def main() -> None:
    await asyncio.to_thread(migrate)
    await fill(datetime.now(UTC))
    print("demo school written")


if __name__ == "__main__":
    # psycopg's async mode needs the selector loop, which Windows does not default to.
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
