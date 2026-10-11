"""The dashboard's own records, Notes and the Suggested grade thresholds, against Postgres."""

import asyncio
import os

import pytest

from classlop.dashboard.reports.grades import THRESHOLDS
from classlop.dashboard.store import PostgresStore
from classlop.shared.migrate import migrate


@pytest.fixture(scope="module", autouse=True)
async def stack():
    try:
        await asyncio.to_thread(migrate)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres")


async def test_a_note_is_kept_per_student_of_a_class_and_replaced_on_saving():
    store = PostgresStore()
    assert await store.note("1a", "s1") == ""

    await store.save_note("1a", "s1", "Rozmowa z rodzicami w listopadzie.")
    await store.save_note("1a", "s2", "Inna notatka.")
    await store.save_note("1a", "s1", "Poprawił kartkówkę.")

    assert await store.note("1a", "s1") == "Poprawił kartkówkę."
    assert await store.note("2c", "s1") == ""


async def test_thresholds_start_at_the_defaults_and_keep_the_teachers():
    store = PostgresStore()
    # Each run has a database of its own, so nothing is saved yet.
    assert await store.thresholds() == list(THRESHOLDS)

    await store.save_thresholds([40, 55, 70, 90, 100])
    assert await store.thresholds() == [40, 55, 70, 90, 100]
    await store.save_thresholds(list(THRESHOLDS))
