"""The demo-school script on the compose stand-ins: what it writes and that a rerun starts clean."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from classlop.dashboard.models import NoteRow
from classlop.grading import results
from classlop.grading.models import CommonMistake
from classlop.shared.db import sessions
from classlop.teams import ids
from classlop.teams.assignment_records import AssignmentRecord, SubmissionRecord
from classlop.teams.demo import CLASSES, STUDENTS_PER_CLASS, student_names
from classlop.teams.models import AttendeeRecord, CalendarEventRecord, ClassRecord, StudentRecord

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)


def script():
    path = Path(__file__).parent.parent / "scripts" / "demo_school.py"
    spec = importlib.util.spec_from_file_location("demo_school", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def count(table) -> int:
    async with sessions()() as session:
        return await session.scalar(select(func.count()).select_from(table)) or 0


@pytest.fixture(scope="module")
async def written(stack):
    await script().fill(NOW)


def test_the_invented_names_are_all_different():
    names = [student_names(n) for n in range(len(CLASSES) * STUDENTS_PER_CLASS)]

    assert len(set(names)) == len(names)


async def test_three_classes_of_25_students_with_one_former_each(written):
    async with sessions()() as session:
        classes = list(await session.scalars(select(ClassRecord).order_by(ClassRecord.name)))
        students = list(await session.scalars(select(StudentRecord)))

    assert [c.name for c in classes] == list(CLASSES)
    assert len(students) == 3 * STUDENTS_PER_CLASS
    assert sum(s.former_since is not None for s in students) == 3


async def test_lessons_have_attendance_and_assignments_have_graded_submissions(written):
    async with sessions()() as session:
        assignments = list(await session.scalars(select(AssignmentRecord)))
        graded = await session.scalar(
            select(func.count())
            .select_from(SubmissionRecord)
            .where(SubmissionRecord.state.in_(["graded", "returned"]))
        )
    found = await results([ids.as_uuid(a.id) for a in assignments])

    assert await count(CalendarEventRecord) > 20
    assert await count(AttendeeRecord) > 100
    assert len(assignments) == 3 * 4
    assert len(found) == graded
    assert any(r.held for r in found) and any(not r.held for r in found)
    assert await count(CommonMistake) > 0
    assert await count(NoteRow) > 0


async def test_rerunning_starts_from_a_clean_slate(written):
    tables = (ClassRecord, StudentRecord, AssignmentRecord, SubmissionRecord, NoteRow)
    before = [await count(t) for t in tables]

    await script().fill(NOW)

    assert [await count(t) for t in tables] == before
