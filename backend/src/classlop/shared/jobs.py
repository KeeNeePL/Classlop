import asyncio
import functools
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterable

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from classlop.shared import llm, queue
from classlop.shared.db import sessions
from classlop.shared.models import Job
from classlop.shared.settings import get_settings

log = logging.getLogger(__name__)

Progress = Callable[[dict], Awaitable[None]]
Handler = Callable[[Job, Progress], Awaitable[dict | None]]

_handlers: dict[str, Handler] = {}


class SignInRequired(Exception):
    """Raised by a handler that needs the Teacher to sign in again; the job waits."""


def handler(kind: str, traced: bool = False) -> Callable[[Handler], Handler]:
    """Register a job kind's handler. A traced kind, one that calls models, makes one trace per
    run; the rest send nothing, so frequent polls do not fill LangSmith with empty traces."""

    def register(fn: Handler) -> Handler:
        @functools.wraps(fn)
        async def run(job: Job, progress: Progress) -> dict | None:
            with llm.trace(kind, job_id=job.id, **job.payload):
                return await fn(job, progress)

        _handlers[kind] = run if traced else fn
        return _handlers[kind]

    return register


async def enqueue(
    kind: str, payload: dict | None = None, *, key: str | None = None, delay: int = 0
) -> uuid.UUID:
    """Write the job row, then send its id, run no sooner than `delay` seconds (at most 900,
    SQS's limit); the same key makes one job."""
    async with sessions().begin() as session:
        created = await session.scalar(
            insert(Job)
            .values(id=uuid.uuid4(), kind=kind, payload=payload or {}, key=key)
            .on_conflict_do_nothing(index_elements=["key"])
            .returning(Job.id)
        )
        if created is None:
            return await session.scalar(select(Job.id).where(Job.key == key))  # type: ignore[return-value]
    await queue.send({"job_id": str(created)}, delay)
    return created


async def get_jobs(ids: Iterable[uuid.UUID]) -> list[Job]:
    async with sessions()() as session:
        return list((await session.scalars(select(Job).where(Job.id.in_(list(ids))))).all())


async def ping(kind: str = "shared.ping", timeout: float = 30) -> bool:
    """Run a payload-less job through the queue and the worker; True if it succeeds."""
    job_id = await enqueue(kind)
    async with asyncio.timeout(timeout):
        while (job := (await get_jobs([job_id]))[0]).status not in (
            "succeeded",
            "failed",
            "waiting_for_sign_in",
        ):
            await asyncio.sleep(0.5)
    print(f"{job.kind} {job_id}: {job.status} {job.result or job.error or ''}")
    return job.status == "succeeded"


async def resume_waiting() -> int:
    """Re-enqueue every job parked for sign-in; call it once the Teacher has signed in."""
    async with sessions().begin() as session:
        ids = (
            await session.scalars(
                update(Job)
                .where(Job.status == "waiting_for_sign_in")
                .values(status="queued")
                .returning(Job.id)
            )
        ).all()
    for job_id in ids:
        await queue.send({"job_id": str(job_id)})
    return len(ids)


async def _set(job_id: uuid.UUID, **values) -> None:
    async with sessions().begin() as session:
        await session.execute(update(Job).where(Job.id == job_id).values(**values))


async def _claim(body: dict) -> Job | None:
    """The job to run for a message, or None if it has already finished."""
    async with sessions().begin() as session:
        if "job_id" in body:
            job = await session.get(Job, uuid.UUID(body["job_id"]))
        else:
            # A timed trigger: the message itself is the job request.
            key = body.get("key")
            job_id = await session.scalar(
                insert(Job)
                .values(
                    id=uuid.uuid4(), kind=body["kind"], payload=body.get("payload", {}), key=key
                )
                .on_conflict_do_nothing(index_elements=["key"])
                .returning(Job.id)
            ) or await session.scalar(select(Job.id).where(Job.key == key))
            job = await session.get(Job, job_id)
        if job is None or job.status in ("succeeded", "failed", "waiting_for_sign_in"):
            return None
        job.status = "running"
        job.attempts += 1
        return job


async def process(message: dict) -> None:
    """Run the job a message names; unfinished work is left for SQS to redeliver."""
    job = await _claim(json.loads(message["Body"]))
    if job is None:
        await queue.delete(message)
        return

    async def progress(value: dict) -> None:
        await _set(job.id, progress=value)

    try:
        result = await _handlers[job.kind](job, progress)
    except SignInRequired:
        await _set(job.id, status="waiting_for_sign_in")
        await queue.delete(message)
    except Exception as exc:
        log.exception("job %s (%s) failed", job.id, job.kind)
        await _set(job.id, status="failed" if job.final_attempt else "queued", error=repr(exc))
        # Not deleted: SQS redelivers it, and after the last receive moves it to the DLQ.
        await queue.retry_in(message, get_settings().jobs_retry_delay)
    else:
        await _set(job.id, status="succeeded", result=result)
        await queue.delete(message)
