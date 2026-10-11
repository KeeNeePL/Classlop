"""The dashboard with the Teacher signed in and no database, for the Playwright tests in
frontend/e2e. The Item bank is a few invented Items in memory; `teams` is FakeTeams with its demo
tenant, and the Notes are in memory."""

from fake_bank import InMemoryBank
from fake_notes import InMemoryNotes
from fastapi import FastAPI

from classlop.dashboard import auth, bank, classes, notes
from classlop.dashboard.app import create_app
from classlop.teams.fake import demo


def create() -> FastAPI:
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    app.dependency_overrides[auth.sign_in_lapsed] = lambda: False
    items = InMemoryBank()
    app.dependency_overrides[bank.backend] = lambda: items
    app.state.teams = demo()
    app.state.notes = InMemoryNotes()
    app.dependency_overrides[classes.backend] = lambda: app.state.teams
    app.dependency_overrides[notes.backend] = lambda: app.state.notes

    # The Playwright tests share this server, so one that changes the bank or the Classes puts it
    # back.
    @app.post("/api/e2e/reset", include_in_schema=False)
    async def reset() -> None:
        items.reset()
        app.state.teams = demo()
        app.state.notes = InMemoryNotes()

    return app
