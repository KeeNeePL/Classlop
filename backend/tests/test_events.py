"""The event stream: job status read from Postgres, pushed as server-sent events."""

import asyncio
import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from classlop.dashboard import events
from classlop.dashboard.app import create_app
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.models import Job


@pytest.fixture
async def feed():
    try:
        await asyncio.to_thread(migrate)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres")
    async with sessions().begin() as session:
        await session.execute(delete(Job))
    yield events.JobFeed()
    async with sessions().begin() as session:
        await session.execute(delete(Job))


async def write(kind: str, **values) -> uuid.UUID:
    job = Job(id=uuid.uuid4(), kind=kind, **values)
    async with sessions().begin() as session:
        session.add(job)
    return job.id


async def change(job_id: uuid.UUID, **values) -> None:
    async with sessions().begin() as session:
        await session.execute(update(Job).where(Job.id == job_id).values(**values))


def parse(frame: str) -> dict:
    return json.loads(next(line[6:] for line in frame.split("\n") if line.startswith("data: ")))


async def next_event(stream) -> dict:
    """The next event of a stream, past its keepalives."""
    async with asyncio.timeout(5):
        while True:
            frame = await anext(stream)
            if "data: " in frame:
                return parse(frame)


def test_the_stream_needs_a_session():
    assert TestClient(create_app()).get("/api/events").status_code == 401


async def test_a_job_finishing_is_pushed_with_its_kind_and_status(feed):
    stream = events.stream(feed, await feed.now(), interval=0.05)
    assert "retry:" in await anext(stream)

    job_id = await write("grading.grade", status="running")
    await change(job_id, status="succeeded")
    done = await next_event(stream)

    assert (done["kind"], done["job_id"], done["status"]) == ("graded", str(job_id), "succeeded")


async def test_a_job_that_has_not_finished_or_has_failed_is_no_news(feed):
    stream = events.stream(feed, await feed.now(), interval=0.05)
    await anext(stream)

    await write("grading.grade", status="running")
    await write("grading.grade", status="failed", error="boom")
    marker = await write("grading.grade", status="succeeded")

    assert (await next_event(stream))["job_id"] == str(marker)


async def test_progress_goes_with_the_event(feed):
    stream = events.stream(feed, await feed.now(), interval=0.05)
    await anext(stream)

    await write("items.generate", status="running", progress={"landed": 3, "total": 8})

    event = await next_event(stream)
    assert (event["kind"], event["progress"]) == ("generation", {"landed": 3, "total": 8})


async def test_only_what_changed_after_the_stream_opened_is_pushed(feed):
    await write("grading.grade", status="succeeded")
    stream = events.stream(feed, await feed.now(), interval=0.05)
    await anext(stream)

    fresh = await write("grading.grade", status="succeeded")

    assert (await next_event(stream))["job_id"] == str(fresh)


async def test_jobs_no_screen_cares_about_stay_silent(feed):
    stream = events.stream(feed, await feed.now(), interval=0.05)
    await anext(stream)

    await write("shared.ping", status="succeeded", result={"pong": True})
    await write("teams.poll_handins", status="succeeded", result={"changed": 0})
    await write("teams.fetch_attendance", status="succeeded", result={"fetched": 0})
    marker = await write("teams.fetch_attendance", status="succeeded", result={"fetched": 2})

    event = await next_event(stream)
    assert (event["kind"], event["job_id"]) == ("attendance", str(marker))


async def test_a_poll_that_found_a_hand_in_is_pushed(feed):
    stream = events.stream(feed, await feed.now(), interval=0.05)
    await anext(stream)

    await write("teams.poll_handins", status="succeeded", result={"changed": 1})

    assert (await next_event(stream))["kind"] == "hand_in"


async def test_a_stream_reconnecting_gets_what_it_missed(feed):
    first = events.stream(feed, await feed.now(), interval=0.05)
    await anext(first)
    seen = await write("grading.grade", status="succeeded")
    last_id = None
    async with asyncio.timeout(5):
        while last_id is None:
            frame = await anext(first)
            if "data: " in frame:
                last_id = next(line[4:] for line in frame.split("\n") if line.startswith("id: "))
    assert parse(frame)["job_id"] == str(seen)

    missed = await write("grading.grade", status="succeeded")
    second = events.stream(feed, events.cursor(last_id), interval=0.05)
    await anext(second)

    assert (await next_event(second))["job_id"] == str(missed)
