"""Timed triggers. Prod: EventBridge Scheduler targeting the jobs queue. Dev: rows in
shared.schedule, fired by the `scheduler` service."""

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import boto3
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from classlop.shared import jobs
from classlop.shared.db import sessions
from classlop.shared.models import Schedule
from classlop.shared.settings import get_settings

_UNITS = {"minute": 60, "hour": 3600, "day": 86400}
_declared: list[tuple[str, str, str, dict]] = []


@lru_cache
def _scheduler():
    s = get_settings()
    secret = s.aws_secret_access_key
    return boto3.client(
        "scheduler",
        region_name=s.aws_region,
        aws_access_key_id=s.aws_access_key_id,
        aws_secret_access_key=secret.get_secret_value() if secret else None,
    )


def _seconds(rate: str) -> int:
    """`rate(5 minutes)`, EventBridge's syntax."""
    match = re.fullmatch(r"rate\((\d+) (minute|hour|day)s?\)", rate)
    if not match:
        raise ValueError(f"unsupported rate: {rate!r}")
    return int(match[1]) * _UNITS[match[2]]


def _in_prod() -> bool:
    return get_settings().schedule_group is not None


def _put(name: str, expression: str, kind: str, payload: dict, key: str | None, **extra) -> None:
    s, client = get_settings(), _scheduler()
    spec = {
        "Name": name,
        "GroupName": s.schedule_group,
        "ScheduleExpression": expression,
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "Target": {
            "Arn": s.jobs_queue_arn,
            "RoleArn": s.schedule_role_arn,
            "Input": json.dumps({"kind": kind, "payload": payload, "key": key}),
        },
        **extra,
    }
    try:
        client.create_schedule(**spec)
    except client.exceptions.ConflictException:
        client.update_schedule(**spec)


async def at(name: str, when: datetime, kind: str, payload: dict) -> None:
    """Fire a job once at `when`; the same name replaces the earlier schedule."""
    when = when.astimezone(UTC)
    if _in_prod():
        await asyncio.to_thread(
            _put,
            name,
            f"at({when:%Y-%m-%dT%H:%M:%S})",
            kind,
            payload,
            f"{name}@{when.isoformat()}",
            ActionAfterCompletion="DELETE",
        )
        return
    await _upsert(name, kind, payload, when, None)


async def every(name: str, rate: str, kind: str, payload: dict) -> None:
    """Fire a job on a rate such as `rate(5 minutes)`; calling it again updates the schedule."""
    seconds = _seconds(rate)
    if _in_prod():
        await asyncio.to_thread(_put, name, rate, kind, payload, None)
        return
    await _upsert(name, kind, payload, datetime.now(UTC) + timedelta(seconds=seconds), seconds)


async def cancel(name: str) -> None:
    if _in_prod():
        client = _scheduler()
        try:
            await asyncio.to_thread(
                client.delete_schedule, Name=name, GroupName=get_settings().schedule_group
            )
        except client.exceptions.ResourceNotFoundException:
            pass
        return
    async with sessions().begin() as session:
        await session.execute(delete(Schedule).where(Schedule.name == name))


def declare_every(name: str, rate: str, kind: str, payload: dict | None = None) -> None:
    """Declare a recurring schedule in code; the worker upserts it when it starts."""
    _declared.append((name, rate, kind, payload or {}))


async def sync_declared() -> None:
    for name, rate, kind, payload in _declared:
        await every(name, rate, kind, payload)


async def _upsert(name: str, kind: str, payload: dict, next_at: datetime, every_seconds):
    values = dict(kind=kind, payload=payload, next_at=next_at, every_seconds=every_seconds)
    async with sessions().begin() as session:
        existing = await session.get(Schedule, name)
        if existing and existing.every_seconds is not None and every_seconds is not None:
            # A restart must not push a running schedule's next fire away.
            values["next_at"] = existing.next_at
        await session.execute(
            insert(Schedule)
            .values(name=name, **values)
            .on_conflict_do_update(index_elements=["name"], set_=values)
        )


async def fire_due() -> int:
    """Dev only: enqueue every schedule whose time has come. Returns how many fired."""
    now = datetime.now(UTC)
    async with sessions().begin() as session:
        due = (
            await session.scalars(
                select(Schedule).where(Schedule.next_at <= now).with_for_update(skip_locked=True)
            )
        ).all()
        for item in due:
            await jobs.enqueue(
                item.kind, item.payload, key=f"{item.name}@{item.next_at.isoformat()}"
            )
            if item.every_seconds is None:
                await session.delete(item)
            else:
                item.next_at = now + timedelta(seconds=item.every_seconds)
    return len(due)


async def run_scheduler(poll_seconds: float = 1) -> None:
    while True:
        await fire_due()
        await asyncio.sleep(poll_seconds)
