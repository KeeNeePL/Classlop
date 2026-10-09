from fastapi.testclient import TestClient

from classlop.dashboard.app import create_app
from classlop.shared import db, search, storage


async def ok() -> None:
    pass


async def down() -> None:
    raise ConnectionError


def test_healthz_reports_every_service(monkeypatch):
    monkeypatch.setattr(db, "ping", ok)
    monkeypatch.setattr(search, "ping", ok)
    monkeypatch.setattr(storage, "ping", lambda: None)

    response = TestClient(create_app()).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"postgres": "ok", "opensearch": "ok", "s3": "ok"}


def test_healthz_fails_when_a_service_is_down(monkeypatch):
    monkeypatch.setattr(db, "ping", ok)
    monkeypatch.setattr(search, "ping", down)
    monkeypatch.setattr(storage, "ping", lambda: None)

    response = TestClient(create_app()).get("/healthz")

    assert response.status_code == 503
    assert response.json()["opensearch"] == "down"
