"""The dashboard with the Teacher signed in and no database, for the Playwright tests in
frontend/e2e. The Item bank is a few invented Items in memory."""

from fake_bank import InMemoryBank
from fastapi import FastAPI

from classlop.dashboard import auth, bank
from classlop.dashboard.app import create_app


def create() -> FastAPI:
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    app.dependency_overrides[auth.sign_in_lapsed] = lambda: False
    items = InMemoryBank()
    app.dependency_overrides[bank.backend] = lambda: items

    # The Playwright tests share this server, so one that changes the bank puts it back.
    @app.post("/api/e2e/reset", include_in_schema=False)
    async def reset() -> None:
        items.reset()

    return app
