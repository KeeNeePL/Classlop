import asyncio
import os
import sys
import uuid

import pytest
from sqlalchemy import delete

# Before any settings are read: private queues, so a running compose worker never steals jobs.
os.environ.setdefault("SQS_ENDPOINT_URL", "http://localhost:9324")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:8333")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "dev")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "dev")
_run = uuid.uuid4().hex[:8]
os.environ["ITEMS_INDEX"] = f"test-items-{_run}"
os.environ["JOBS_QUEUE"] = f"test-jobs-{_run}"
os.environ["JOBS_DLQ"] = f"test-jobs-dlq-{_run}"
os.environ["JOBS_VISIBILITY_TIMEOUT"] = "5"
os.environ["JOBS_RETRY_DELAY"] = "1"

if sys.platform == "win32":
    # psycopg's async mode cannot run on the default Proactor loop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fake_graph import FakeGraph  # noqa: E402
from tenant import TEACHER, Clock, Tenant, ignore  # noqa: E402

from classlop import items  # noqa: E402
from classlop.shared import queue  # noqa: E402
from classlop.shared.db import sessions  # noqa: E402
from classlop.shared.jobs import SignInRequired  # noqa: E402
from classlop.shared.migrate import migrate  # noqa: E402
from classlop.shared.models import Schedule  # noqa: E402
from classlop.shared.settings import get_settings  # noqa: E402
from classlop.teams.fake import FakeTeams  # noqa: E402
from classlop.teams.graph import GraphClient  # noqa: E402
from classlop.teams.handin_records import HandinCursor  # noqa: E402
from classlop.teams.models import (  # noqa: E402
    CalendarCursor,
    CalendarSeriesRecord,
    ClassRecord,
    SettingRecord,
)
from classlop.teams.service import GraphTeams  # noqa: E402


# The `teams` tests: the stand-ins they need, the Teacher, a clock and a tenant to drive.
@pytest.fixture(scope="module")
async def stack():
    try:
        await asyncio.to_thread(migrate)
        await asyncio.to_thread(queue.url)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres elasticmq")


@pytest.fixture
async def teacher(monkeypatch, stack):
    monkeypatch.setattr(get_settings(), "m365_teacher_oid", TEACHER)
    async with sessions().begin() as session:
        # Assignments and their Submissions go with their Class.
        for table in (
            ClassRecord,
            SettingRecord,
            CalendarSeriesRecord,
            CalendarCursor,
            HandinCursor,
        ):
            await session.execute(delete(table))
        await session.execute(delete(Schedule).where(Schedule.name.like("teams.give:%")))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture(params=["graph", "fake"])
def tenant(request, clock, teacher):
    """The area under test, which is also where the test seeds its invented tenant."""
    if request.param == "fake":
        return FakeTeams(clock=clock)
    graph = FakeGraph(TEACHER, clock)
    tenant = Tenant(graph)

    async def token() -> str:
        if tenant.lapsed:
            raise SignInRequired
        return "token"

    client = GraphClient(token=token, transport=graph.transport, sleep=ignore)
    tenant.area = GraphTeams(client, clock=clock, records=client)
    return tenant


@pytest.fixture
def gave(monkeypatch) -> list[tuple]:
    """Every call to `items.give`, which pins each Item to a version of its own."""
    calls: list[tuple] = []

    async def give(item_ids, assignment_id, class_id, given_at):
        calls.append((item_ids, assignment_id, class_id, given_at))
        return [uuid.UUID(int=i.int + 100) for i in item_ids]

    monkeypatch.setattr(items, "give", give)
    return calls
