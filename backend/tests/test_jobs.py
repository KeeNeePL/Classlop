"""Jobs, worker and scheduler against the compose stand-ins (postgres and elasticmq)."""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select

from classlop.shared import jobs, queue, schedule, worker
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.models import Job, Schedule
from classlop.shared.settings import get_settings
from classlop.teams.graph import BASE, MAX_TRIES, GraphClient


@pytest.fixture(scope="session", autouse=True)
async def stack():
    try:
        await asyncio.to_thread(migrate)
        await asyncio.to_thread(queue.url)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres elasticmq")
    # Started once: cancelling a worker mid-receive would leave an orphaned receive that
    # steals a message and burns one of its three receives.
    tasks = [asyncio.create_task(run_worker()), asyncio.create_task(schedule.run_scheduler())]
    yield
    for task in tasks:
        task.cancel()


async def run_worker():
    worker.load_handlers()
    while True:
        for message in await queue.receive(wait_seconds=1):
            await jobs.process(message)


async def until(predicate, timeout=20):
    async with asyncio.timeout(timeout):
        while not (value := await predicate()):
            await asyncio.sleep(0.2)
    return value


async def job_of(job_id):
    return (await jobs.get_jobs([job_id]))[0]


async def jobs_of(kind):
    async with sessions()() as session:
        return (await session.scalars(select(Job).where(Job.kind == kind))).all()


def new_kind() -> str:
    return f"test.{uuid.uuid4().hex[:8]}"


async def test_ping_ends_succeeded():
    assert await jobs.ping()


async def test_same_key_makes_one_job():
    kind, key = new_kind(), uuid.uuid4().hex

    first = await jobs.enqueue(kind, {"n": 1}, key=key)
    second = await jobs.enqueue(kind, {"n": 2}, key=key)

    assert first == second
    async with sessions()() as session:
        count = await session.scalar(select(func.count()).select_from(Job).where(Job.kind == kind))
    assert count == 1


async def test_progress_is_readable_while_the_handler_runs():
    kind, release = new_kind(), asyncio.Event()

    @jobs.handler(kind)
    async def slow(job, progress):
        await progress({"done": 1, "total": 2})
        await release.wait()
        return {"ok": True}

    async def with_progress():
        job = await job_of(job_id)
        return job if job.progress else None

    async def finished():
        job = await job_of(job_id)
        return job if job.status == "succeeded" else None

    job_id = await jobs.enqueue(kind)
    job = await until(with_progress)
    assert (job.status, job.progress) == ("running", {"done": 1, "total": 2})

    release.set()
    job = await until(finished)
    assert (job.result, job.attempts) == ({"ok": True}, 1)


async def test_a_handler_that_keeps_failing_ends_failed_in_the_dlq():
    kind = new_kind()

    @jobs.handler(kind)
    async def broken(job, progress):
        raise RuntimeError("boom")

    async def failed():
        job = await job_of(job_id)
        return job if job.status == "failed" else None

    async def in_dlq():
        response = await asyncio.to_thread(
            queue._client().receive_message,
            QueueUrl=queue.dlq_url(),
            MaxNumberOfMessages=10,
            WaitTimeSeconds=1,
        )
        bodies = [json.loads(m["Body"]) for m in response.get("Messages", [])]
        return {"job_id": str(job_id)} in bodies

    job_id = await jobs.enqueue(kind)
    job = await until(failed)
    assert job.attempts == 3
    assert "boom" in job.error
    await until(in_dlq, timeout=30)


async def test_a_handler_knows_when_it_is_on_its_final_attempt():
    kind, seen = new_kind(), []

    @jobs.handler(kind)
    async def broken(job, progress):
        seen.append(job.final_attempt)
        raise RuntimeError("boom")

    async def failed():
        return (await job_of(job_id)).status == "failed"

    job_id = await jobs.enqueue(kind)
    await until(failed)
    assert seen == [False, False, True]


async def test_sign_in_required_parks_the_job_until_resumed():
    kind, signed_in = new_kind(), False

    @jobs.handler(kind)
    async def needs_teams(job, progress):
        if not signed_in:
            raise jobs.SignInRequired
        return {"ok": True}

    def status_is(status):
        async def check():
            return (await job_of(job_id)).status == status

        return check

    job_id = await jobs.enqueue(kind)
    await until(status_is("waiting_for_sign_in"))
    await asyncio.sleep(3)
    assert (await job_of(job_id)).status == "waiting_for_sign_in"

    signed_in = True
    assert await jobs.resume_waiting() >= 1
    await until(status_is("succeeded"))


async def test_at_fires_once_and_cancel_stops_it():
    fires, cancelled = new_kind(), new_kind()
    soon = datetime.now(UTC) + timedelta(seconds=1)

    async def fired():
        return await jobs_of(fires)

    await schedule.at(f"at-{fires}", soon, fires, {"x": 1})
    await schedule.at(f"at-{cancelled}", soon, cancelled, {})
    await schedule.cancel(f"at-{cancelled}")
    (job,) = await until(fired)
    await asyncio.sleep(2)

    assert job.payload == {"x": 1}
    assert len(await jobs_of(fires)) == 1
    assert await jobs_of(cancelled) == []


async def test_every_is_upserted_not_duplicated():
    name, kind = f"every-{new_kind()}", new_kind()

    await schedule.every(name, "rate(5 minutes)", kind, {})
    async with sessions()() as session:
        first = (await session.get_one(Schedule, name)).next_at
    await schedule.every(name, "rate(5 minutes)", kind, {})

    async with sessions()() as session:
        rows = (await session.scalars(select(Schedule).where(Schedule.kind == kind))).all()
    assert [(r.name, r.every_seconds, r.next_at) for r in rows] == [(name, 300, first)]
    await schedule.cancel(name)


class StubScheduler:
    class exceptions:
        class ConflictException(Exception): ...

        class ResourceNotFoundException(Exception): ...

    def __init__(self):
        self.calls = []
        self.known = set()

    def create_schedule(self, **kwargs):
        self.calls.append(("create", kwargs))
        if kwargs["Name"] in self.known:
            raise self.exceptions.ConflictException
        self.known.add(kwargs["Name"])

    def update_schedule(self, **kwargs):
        self.calls.append(("update", kwargs))

    def delete_schedule(self, **kwargs):
        self.calls.append(("delete", kwargs))


async def test_prod_schedules_go_to_eventbridge_with_the_queue_as_target(monkeypatch):
    stub, settings = StubScheduler(), get_settings()
    monkeypatch.setattr(schedule, "_scheduler", lambda: stub)
    monkeypatch.setattr(settings, "schedule_group", "classlop")
    monkeypatch.setattr(settings, "schedule_role_arn", "arn:aws:iam::1:role/scheduler")
    monkeypatch.setattr(settings, "jobs_queue_arn", "arn:aws:sqs:eu-central-1:1:jobs")

    await schedule.at("close-7", datetime(2026, 10, 9, 14, 30, tzinfo=UTC), "k", {"a": 1})
    await schedule.every("poll", "rate(5 minutes)", "k", {})
    await schedule.every("poll", "rate(5 minutes)", "k", {})
    await schedule.cancel("close-7")

    assert [verb for verb, _ in stub.calls] == ["create", "create", "create", "update", "delete"]
    at_call, update_call, delete_call = stub.calls[0][1], stub.calls[3][1], stub.calls[4][1]
    assert at_call["GroupName"] == "classlop"
    assert at_call["ScheduleExpression"] == "at(2026-10-09T14:30:00)"
    assert at_call["Target"]["Arn"] == "arn:aws:sqs:eu-central-1:1:jobs"
    assert at_call["Target"]["RoleArn"] == "arn:aws:iam::1:role/scheduler"
    assert json.loads(at_call["Target"]["Input"])["kind"] == "k"
    assert update_call["ScheduleExpression"] == "rate(5 minutes)"
    assert delete_call == {"Name": "close-7", "GroupName": "classlop"}


async def _no_sleep(seconds: float) -> None:
    pass


async def _token() -> str:
    return "token"


@respx.mock
async def test_a_job_throttled_out_of_its_tries_goes_back_to_the_queue_and_then_succeeds():
    kind, route = new_kind(), respx.get(f"{BASE}/me")
    route.mock(side_effect=[httpx.Response(429)] * MAX_TRIES + [httpx.Response(200, json={})])

    @jobs.handler(kind)
    async def whoami(job, progress):
        await GraphClient(token=_token, sleep=_no_sleep).get("/me")
        return {"ok": True}

    job_id = await jobs.enqueue(kind)

    async def succeeded():
        return (await job_of(job_id)).status == "succeeded"

    await until(succeeded)
    job = await job_of(job_id)
    assert (job.attempts, route.call_count) == (2, MAX_TRIES + 1)


@respx.mock
async def test_a_graph_call_the_teacher_must_sign_in_for_waits_and_resumes():
    kind, route = new_kind(), respx.get(f"{BASE}/me")
    route.mock(side_effect=[httpx.Response(401), httpx.Response(200, json={})])

    @jobs.handler(kind)
    async def whoami(job, progress):
        await GraphClient(token=_token, sleep=_no_sleep).get("/me")

    job_id = await jobs.enqueue(kind)

    async def waiting():
        return (await job_of(job_id)).status == "waiting_for_sign_in"

    async def succeeded():
        return (await job_of(job_id)).status == "succeeded"

    await until(waiting)
    assert await jobs.resume_waiting() >= 1
    await until(succeeded)
