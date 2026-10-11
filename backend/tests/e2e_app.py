"""The dashboard with the Teacher signed in and no database, for the Playwright tests in
frontend/e2e. The Item bank is a few invented Items in memory; one invented job can be finished."""

from fake_bank import InMemoryBank
from fake_events import InMemoryFeed
from fake_work import Offline, invented_class
from fastapi import FastAPI

from classlop import teams
from classlop.dashboard import auth, bank, events, home, new_work
from classlop.dashboard.app import create_app
from classlop.teams.fake import FakeTeams


def create() -> FastAPI:
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    app.dependency_overrides[auth.sign_in_lapsed] = lambda: False
    items = InMemoryBank()
    app.dependency_overrides[bank.backend] = lambda: items
    feed = InMemoryFeed()
    app.dependency_overrides[events.job_feed] = lambda: feed
    app.dependency_overrides[home.stand_in] = lambda: feed.home
    app.dependency_overrides[home.failed_gives] = lambda: []

    # The Playwright tests share this server, so one that changes the bank puts it back.
    @app.post("/api/e2e/reset", include_in_schema=False)
    async def reset() -> None:
        items.reset()
        feed.reset()

    @app.post("/api/e2e/grade", include_in_schema=False)
    async def grade() -> None:
        feed.grade()

    return app


def serve() -> FastAPI:
    """`create()` for the Playwright server, with giving over FakeTeams: the invented Class 1A of
    the sidebar is a Class of FakeTeams, whose giving asks `items`, the scheduler and the job
    queue nothing a database is needed for."""
    app = create()
    items = app.dependency_overrides[bank.backend]()
    fake = FakeTeams()
    teams._backend = fake
    for module, name, replacement in Offline(items).patches():
        setattr(module, name, replacement)
    linked: list[str] = []

    async def team_class(class_id: str) -> str:
        if class_id != "1a":
            return class_id
        if not linked:
            linked.append((await invented_class(fake)).id)
        return linked[0]

    app.dependency_overrides[new_work.team_class] = team_class

    # A POST: the app's catch-all GET route comes first.
    @app.post("/api/e2e/posts", include_in_schema=False)
    async def posts() -> list[str]:
        """The files posted in General, by name."""
        return [name for team in fake._teams for p in fake.channel_posts(team) for name in p.files]

    return app
