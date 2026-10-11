"""The event stream's `Feed` in memory, with one invented job, for the Playwright server, which
runs without a database."""

import uuid
from datetime import UTC, datetime

from classlop.dashboard.events import Event
from classlop.dashboard.home import Entry, Home, invented


class InMemoryFeed:
    def __init__(self) -> None:
        self.events: list[Event] = []
        self.graded = False

    def reset(self) -> None:
        self.events.clear()
        self.graded = False

    async def now(self) -> datetime:
        return datetime.now(UTC)

    async def since(self, cursor: datetime) -> list[Event]:
        return [e for e in self.events if e.at > cursor]

    def grade(self) -> None:
        """The invented job: the worker finishes grading an Assignment of 1A."""
        self.graded = True
        self.events.append(
            Event(
                kind="graded",
                job_id=str(uuid.uuid4()),
                status="succeeded",
                progress=None,
                at=datetime.now(UTC),
            )
        )

    def home(self, now: datetime) -> Home:
        """The invented home, with the graded Assignment in the queue once the job has finished."""
        view = invented(now)
        if not self.graded:
            return view
        entry = Entry(
            kind="graded",
            title="Ocenione przez AI: Pierwiastki (1A)",
            detail="Praca domowa, średnio 80%, oddane 25/25",
            link="/klasy/1a/prace/pierwiastki",
            action="Zobacz",
        )
        return view.model_copy(update={"entries": view.entries + [entry]})
