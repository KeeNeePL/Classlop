"""The dashboard's Notes in Postgres: deleting a Class takes its Notes and no other Class's."""

import asyncio
import os

import pytest
from sqlalchemy import delete, select

from classlop.dashboard.models import NoteRecord
from classlop.dashboard.notes import NoteTable
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate


@pytest.fixture
async def table():
    try:
        await asyncio.to_thread(migrate)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres")
    async with sessions().begin() as session:
        await session.execute(delete(NoteRecord))
    yield
    async with sessions().begin() as session:
        await session.execute(delete(NoteRecord))


async def test_deleting_a_class_deletes_its_notes_only(table):
    async with sessions().begin() as session:
        session.add_all(
            [
                NoteRecord(class_id="4D", student_id="a", text="spokojny"),
                NoteRecord(class_id="4D", student_id="b", text="pracowity"),
                NoteRecord(class_id="4E", student_id="c", text="uważny"),
            ]
        )

    await NoteTable().delete_class("4D")

    async with sessions().begin() as session:
        left = (await session.execute(select(NoteRecord.class_id, NoteRecord.student_id))).all()
    assert [tuple(r) for r in left] == [("4E", "c")]
