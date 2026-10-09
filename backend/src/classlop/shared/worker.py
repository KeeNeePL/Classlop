import asyncio
import logging
from importlib import import_module
from importlib.util import find_spec

from classlop.shared import jobs, queue, schedule
from classlop.shared.db import SCHEMAS

log = logging.getLogger(__name__)


def load_handlers() -> None:
    for area in SCHEMAS:
        if find_spec(f"classlop.{area}.handlers"):
            import_module(f"classlop.{area}.handlers")


async def run() -> None:
    load_handlers()
    await asyncio.to_thread(queue.url)
    await schedule.sync_declared()
    log.info("worker ready")
    while True:
        for message in await queue.receive():
            await jobs.process(message)
