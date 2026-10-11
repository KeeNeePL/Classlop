"""The Class overview endpoint, over HTTP with the Teacher signed in."""

import uuid

import pytest
from e2e_app import create
from fake_bank import InMemoryBank
from fastapi.testclient import TestClient

from classlop.dashboard import bank, invented
from classlop.dashboard.app import create_app
from classlop.items import ItemVersion


def test_overview_needs_a_session():
    assert TestClient(create_app()).get("/api/classes/2c/overview").status_code == 401


def test_overview_is_ready_for_the_screen_and_marked_invented():
    view = TestClient(create()).get("/api/classes/2c/overview").json()

    assert view["name"] == "2C"
    assert view["invented"] is True
    assert [c["type"] for c in view["progress"]] == ["quiz", "exam", "homework"]
    assert all(c["average"] is not None for c in view["progress"])
    sections = view["progress"][0]["sections"]
    assert [s["name"] for s in sections][:2] == ["Liczby rzeczywiste", "Wyrażenia algebraiczne"]
    assert any(s["percent"] is None for s in sections)
    assert any(s["percent"] is not None for s in sections)
    assert view["assignments"] and view["students"]
    # The newest Assignment, still open, covers sections V and VI; the oldest, I.
    assert view["recent_sections"] == [
        "lo2024:V",
        "lo2024:VI",
        "lo2024:IV",
        "lo2024:III",
        "lo2024:II",
        "lo2024:I",
    ]
    assert all(a["average"] is not None for a in view["assignments"])
    given = [a["given_at"] for a in view["assignments"]]
    assert given == sorted(given, reverse=True)
    assert any(s["former"] for s in view["students"])
    assert 0 < len(view["attention"]) <= 5
    assert all(a["reasons"] for a in view["attention"])


class CountingBank(InMemoryBank):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[uuid.UUID]] = []

    async def versions(self, version_ids: list[uuid.UUID]) -> list[ItemVersion]:
        self.calls.append(version_ids)
        return await super().versions(version_ids)


def test_the_item_versions_come_from_the_bank_in_one_call():
    pool = CountingBank()
    app = create()
    app.dependency_overrides[bank.backend] = lambda: pool

    TestClient(app).get("/api/classes/2c/overview")

    # Five Assignments: sections I-II, II-III, III-IV, IV-V and V-VI of the invented bank.
    assert len(pool.calls) == 1 and len(pool.calls[0]) == 2 + 3 + 3 + 2 + 2


@pytest.fixture
def unpinned():
    invented.reset()
    yield
    invented.reset()


def without_section_one() -> InMemoryBank:
    """The invented bank as if its one Item of section I had never been written."""
    pool = InMemoryBank()
    (gone,) = [i for i in pool.items.values() if i.version.text == "Ile to $2^3 - 6$?"]
    del pool.items[gone.id]
    del pool._versions[gone.version.id]
    return pool


def overview(pool: InMemoryBank) -> dict:
    app = create()
    app.dependency_overrides[bank.backend] = lambda: pool
    return TestClient(app).get("/api/classes/2c/overview").json()


def test_progress_follows_the_tags_of_the_banks_items(unpinned):
    view = overview(without_section_one())

    # Without the bank's one Item of section I, nothing in it is assessed.
    assert "lo2024:I" not in view["recent_sections"]
    assert view["progress"][0]["sections"][0]["percent"] is None


def test_a_bank_that_lost_a_pinned_version_is_pinned_afresh(unpinned):
    assert "lo2024:I" in overview(InMemoryBank())["recent_sections"]

    assert "lo2024:I" not in overview(without_section_one())["recent_sections"]


def test_the_sidebars_classes_each_have_an_overview_and_others_are_unknown():
    web = TestClient(create())

    assert [web.get(f"/api/classes/{c}/overview").status_code for c in ("1a", "2c", "3b")] == [
        200
    ] * 3
    assert web.get("/api/classes/9z/overview").status_code == 404
