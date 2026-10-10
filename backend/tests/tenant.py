"""What every `teams` test file shares: the clock and the tenant a test seeds and drives."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fake_graph import FakeGraph

from classlop import teams

TEACHER = "teacher-oid"
WARSAW = ZoneInfo("Europe/Warsaw")
PDF = b"%PDF-1.7 funkcje liniowe"
DUE = datetime(2026, 9, 15, 20, 0, tzinfo=WARSAW)
CLOSE = datetime(2026, 9, 17, 20, 0, tzinfo=WARSAW)
ITEMS = [uuid.UUID(int=1), uuid.UUID(int=2)]


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)


async def ignore(_):
    """A progress callback, and the sleep of a client that must not wait."""


class Tenant:
    """The real area plus the fake Microsoft behind it. Whatever the area does not have, such as
    the seeding and inspecting methods, is FakeGraph's, which FakeTeams mirrors by name."""

    def __init__(self, graph: FakeGraph):
        self.graph, self.lapsed = graph, False

    def lapse_sign_in(self) -> None:
        self.lapsed = True

    def __getattr__(self, name):
        for target in (self.area, self.graph):
            if hasattr(target, name):
                return getattr(target, name)
        raise AttributeError(name)


def spec(**changes) -> teams.AssignmentSpec:
    """An Assignment on two Items, due on the 15th and closing on the 17th."""
    fields = dict(
        title="Funkcje liniowe", type="homework", due_at=DUE, close_at=CLOSE, item_ids=ITEMS
    )
    return teams.AssignmentSpec(**{**fields, **changes})


async def make_class(tenant, *names: str):
    """A Class linked to a new team with these Students; returns it and their user ids by name."""
    team = tenant.add_team("2A matematyka")
    users = {name: tenant.add_member(team, name) for name in names}
    return await tenant.link_team(team), users
