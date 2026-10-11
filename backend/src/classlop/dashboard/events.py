"""The event stream: one server-sent event stream per browser tab, fed by job status in Postgres.
A screen refetches its view when an event of a kind it shows arrives."""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from classlop.dashboard import auth
from classlop.shared.db import sessions
from classlop.shared.models import Job

router = APIRouter()

INTERVAL = 2.0
# An idle stream says so now and then, so no proxy closes it.
KEEPALIVE = 15.0

EventKind = Literal["hand_in", "graded", "generation", "attendance"]


class Event(BaseModel):
    kind: EventKind
    job_id: str
    status: str
    progress: dict | None
    at: datetime


def _found(key: str) -> Callable[[Job], bool]:
    """A finished job that changed something; a poll that found nothing is no news."""
    return lambda job: job.status == "succeeded" and bool((job.result or {}).get(key))


def _finished(job: Job) -> bool:
    return job.status == "succeeded"


def _always(job: Job) -> bool:
    return True


# The jobs a screen shows, by job kind: the event kind and when a job of it is news. Upload
# progress joins when Item upload becomes a job.
CONCERNS: dict[str, tuple[EventKind, Callable[[Job], bool]]] = {
    "teams.poll_handins": ("hand_in", _found("changed")),
    "grading.grade": ("graded", _always),
    "items.generate": ("generation", _always),
    "teams.fetch_attendance": ("attendance", _found("fetched")),
}


class Feed(Protocol):
    async def now(self) -> datetime: ...

    async def since(self, cursor: datetime) -> list[Event]:
        """The events of what changed after `cursor`, oldest first."""
        ...


class JobFeed:
    async def now(self) -> datetime:
        async with sessions()() as session:
            return await session.scalar(select(func.now()))  # type: ignore[return-value]

    async def since(self, cursor: datetime) -> list[Event]:
        async with sessions()() as session:
            rows = await session.scalars(
                select(Job)
                .where(Job.updated_at > cursor, Job.kind.in_(CONCERNS))
                .order_by(Job.updated_at)
            )
            return [
                Event(
                    kind=CONCERNS[job.kind][0],
                    job_id=str(job.id),
                    status=job.status,
                    progress=job.progress,
                    at=job.updated_at,
                )
                for job in rows
                if CONCERNS[job.kind][1](job)
            ]


def frame(event: Event) -> str:
    """The event's id is its time: a reconnecting browser sends it back as `Last-Event-ID`."""
    return f"id: {event.at.isoformat()}\ndata: {event.model_dump_json()}\n\n"


def cursor(last_event_id: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(last_event_id).astimezone(UTC) if last_event_id else None
    except ValueError:
        return None


async def stream(feed: Feed, after: datetime, interval: float = INTERVAL) -> AsyncIterator[str]:
    yield f"retry: {round(interval * 1000)}\n\n"
    idle = 0.0
    while True:
        for event in await feed.since(after):
            after = max(after, event.at)
            idle = 0.0
            yield frame(event)
        if idle >= KEEPALIVE:
            idle = 0.0
            yield ": keepalive\n\n"
        await asyncio.sleep(interval)
        idle += interval


def job_feed() -> Feed:
    return JobFeed()


@router.get("/api/events", include_in_schema=False)
async def events(
    request: Request,
    _: Annotated[auth.Me, Depends(auth.teacher)],
    feed: Annotated[Feed, Depends(job_feed)],
) -> StreamingResponse:
    after = cursor(request.headers.get("last-event-id")) or await feed.now()
    return StreamingResponse(
        stream(feed, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
