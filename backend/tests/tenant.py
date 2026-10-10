"""What every `teams` test file shares: the clock and the tenant a test seeds and drives."""

from datetime import UTC, datetime, timedelta

from fake_graph import FakeGraph

TEACHER = "teacher-oid"


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
