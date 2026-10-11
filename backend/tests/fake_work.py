"""Giving an Assignment without a database or a queue, for the Nowa praca tests and the Playwright
server: FakeTeams with an invented Class, and what its giving asks of `items`, the scheduler and
the job queue answered in memory."""

import uuid
from collections.abc import Callable
from datetime import datetime
from types import ModuleType

from fake_bank import InMemoryBank

from classlop import items
from classlop.shared import jobs, schedule
from classlop.teams.fake import FakeTeams
from classlop.teams.types import Class

CLASS_NAME = "1A"
STUDENTS = ("Ala Kowalska", "Bartek Nowicki", "Celina Wrona")


async def invented_class(fake: FakeTeams) -> Class:
    team = fake.add_team(CLASS_NAME)
    for name in STUDENTS:
        fake.add_member(team, name)
    return await fake.link_team(team)


class Offline:
    """The calls FakeTeams' giving makes to the areas below it."""

    def __init__(self, bank: InMemoryBank):
        self.bank = bank
        self.scheduled: dict[str, datetime] = {}

    async def give(
        self,
        item_ids: list[uuid.UUID],
        assignment_id: uuid.UUID,
        class_id: uuid.UUID,
        given_at: datetime,
    ) -> list[uuid.UUID]:
        return self.bank.give(item_ids, class_id)

    async def at(self, name: str, when: datetime, kind: str, payload: dict) -> None:
        self.scheduled[name] = when

    async def cancel(self, name: str) -> None:
        self.scheduled.pop(name, None)

    async def enqueue(self, *args, **kwargs) -> uuid.UUID:
        return uuid.uuid4()

    def patches(self) -> list[tuple[ModuleType, str, Callable]]:
        return [
            (items, "give", self.give),
            (schedule, "at", self.at),
            (schedule, "cancel", self.cancel),
            (jobs, "enqueue", self.enqueue),
        ]
