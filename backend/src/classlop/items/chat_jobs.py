"""The jobs a Chat started, for its job cards: Generation requests and Item uploads."""

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.sql.elements import ColumnElement

from classlop.items.upload import PendingDuplicate, pending_duplicates
from classlop.shared.db import sessions
from classlop.shared.models import Job

KINDS = {"items.generate": "generation", "items.upload": "upload"}
RUNNING = ("queued", "running")


class ChatJob(BaseModel):
    job_id: uuid.UUID
    kind: Literal["generation", "upload"]
    status: str
    progress: dict | None
    filename: str | None = None
    # The Items the job added, once it has finished.
    item_ids: list[uuid.UUID] = []
    # Upload only: near-duplicates waiting for the Teacher's decision.
    pending: list[PendingDuplicate] = []


def _ids_of(job: Job) -> list[uuid.UUID]:
    result = job.result or {}
    if job.kind == "items.generate":
        found = [i for line in result.get("lines", []) for i in line]
    else:
        found = [e["item_id"] for e in result.get("items", [])]
    return [uuid.UUID(i) for i in found]


def _of_chat(chat_id: str) -> ColumnElement[bool]:
    return or_(
        Job.payload["chat_id"].astext == chat_id,
        Job.payload["origin"]["chat_id"].astext == chat_id,
    )


async def chat_jobs(chat_id: str) -> list[ChatJob]:
    async with sessions()() as session:
        rows = list(
            await session.scalars(
                select(Job)
                .where(Job.kind.in_(KINDS), _of_chat(chat_id))
                .order_by(Job.created_at, Job.id)
            )
        )
    return [
        ChatJob(
            job_id=job.id,
            kind=KINDS[job.kind],  # type: ignore[arg-type]
            status=job.status,
            progress=job.progress,
            filename=job.payload.get("filename"),
            item_ids=_ids_of(job),
            pending=(
                await pending_duplicates(uuid.UUID(job.payload["upload_id"]))
                if job.kind == "items.upload" and job.status == "succeeded"
                else []
            ),
        )
        for job in rows
    ]


async def running_jobs() -> dict[str, int]:
    """How many jobs run for each Chat that has some."""
    async with sessions()() as session:
        rows = await session.scalars(
            select(Job).where(Job.kind.in_(KINDS), Job.status.in_(RUNNING))
        )
    counts: dict[str, int] = {}
    for job in rows:
        chat_id = job.payload.get("chat_id") or job.payload.get("origin", {}).get("chat_id")
        if chat_id:
            counts[chat_id] = counts.get(chat_id, 0) + 1
    return counts
