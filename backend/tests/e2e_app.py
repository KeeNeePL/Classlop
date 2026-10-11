"""The dashboard with the Teacher signed in and no database, for the Playwright tests in
frontend/e2e. The Item bank is a few invented Items in memory; one invented job can be finished."""

from fake_bank import InMemoryBank
from fake_events import InMemoryFeed
from fastapi import FastAPI

from classlop.dashboard import auth, bank, events, home
from classlop.dashboard.app import create_app


def create() -> FastAPI:
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    app.dependency_overrides[auth.sign_in_lapsed] = lambda: False
    items = InMemoryBank()
    app.dependency_overrides[bank.backend] = lambda: items
    feed = InMemoryFeed()
    app.dependency_overrides[events.job_feed] = lambda: feed
    app.dependency_overrides[home.stand_in] = lambda: feed.home

    # The Playwright tests share this server, so one that changes the bank puts it back.
    @app.post("/api/e2e/reset", include_in_schema=False)
    async def reset() -> None:
        items.reset()
        feed.reset()

    @app.post("/api/e2e/grade", include_in_schema=False)
    async def grade() -> None:
        feed.grade()

    return app
