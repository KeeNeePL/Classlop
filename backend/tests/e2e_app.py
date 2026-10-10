"""The dashboard with the Teacher signed in and no database, for the Playwright tests in
frontend/e2e."""

from fastapi import FastAPI

from classlop.dashboard import auth
from classlop.dashboard.app import create_app


def create() -> FastAPI:
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    app.dependency_overrides[auth.sign_in_lapsed] = lambda: False
    return app
