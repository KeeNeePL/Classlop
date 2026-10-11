"""The Bank zadań endpoints, over HTTP with the Teacher signed in and the bank in memory."""

import uuid

from e2e_app import create
from fake_bank import CLASSES
from fastapi.testclient import TestClient

from classlop.dashboard.app import create_app

OPEN_ITEM = uuid.UUID(int=1001)  # open, Rownania kwadratowe, used with 2C
CLOSED_FLAGGED = uuid.UUID(int=1002)
RETIRED = uuid.UUID(int=1007)


def web() -> TestClient:
    return TestClient(create())


def found(web: TestClient, **params) -> list[str]:
    response = web.get("/api/bank/items", params=params)
    assert response.status_code == 200
    return [i["version"]["text"] for i in response.json()["items"]]


def test_the_bank_needs_a_session():
    web = TestClient(create_app())

    assert web.get("/api/bank/items").status_code == 401
    assert web.get("/api/bank/filters").status_code == 401
    assert web.patch(f"/api/bank/items/{OPEN_ITEM}", json={"text": "x"}).status_code == 401
    assert web.post(f"/api/bank/items/{OPEN_ITEM}/retire").status_code == 401


def test_a_search_lists_the_newest_items_and_leaves_out_the_retired():
    page = web().get("/api/bank/items").json()

    assert page["total"] == 7
    assert page["items"][0]["version"]["text"] == "Ile pierwiastków ma $x^2 + 1$?"
    assert all(not i["retired"] for i in page["items"])


def test_retired_items_are_listed_only_when_asked_for():
    assert len(found(web(), show_retired=True)) == 8


def test_a_search_pages_through_the_items():
    second = web().get("/api/bank/items", params={"size": 3, "page": 3}).json()

    assert (second["total"], second["page"], len(second["items"])) == (7, 3, 1)


def test_the_words_and_every_filter_narrow_the_search():
    client = web()

    assert found(client, q="równanie") == [r"Rozwiąż równanie $x^2 - 4x - 5 = 0$."]
    assert len(found(client, difficulty=["easy"])) == 2
    assert len(found(client, difficulty=["easy", "hard"])) == 4
    assert len(found(client, item_format="closed")) == 4
    assert len(found(client, flagged=True)) == 4
    assert len(found(client, topic=["lo2024:III.4"])) == 2
    assert len(found(client, section=["lo2024:II"])) == 1
    assert found(client, section=["lo2024:II"], show_retired=True).__len__() == 2


def test_never_used_with_a_class_leaves_out_what_the_class_got():
    class_1a, class_2c = (c.id for c in CLASSES[:2])

    assert len(found(web(), never_used_with_class=str(class_2c))) == 6
    assert len(found(web(), never_used_with_class=str(class_1a))) == 6
    assert len(found(web(), never_used_with_class=str(uuid.uuid4()))) == 7


def test_the_filters_are_the_curriculum_and_the_classes():
    filters = web().get("/api/bank/filters").json()

    assert filters["sections"][0]["name"] == "Liczby rzeczywiste"
    assert filters["sections"][0]["topics"][0]["id"] == "lo2024:I.1"
    assert [c["name"] for c in filters["classes"]] == ["1A", "2C", "3B"]


def test_an_items_detail_has_its_solution_rubric_tags_and_usage():
    detail = web().get(f"/api/bank/items/{OPEN_ITEM}").json()

    version = detail["item"]["version"]
    assert version["model_solution"].startswith(r"$\Delta = 36$")
    assert [level["points"] for level in version["rubric"]] == [1, 2]
    assert version["points"] == 2 and version["difficulty"] == "medium"
    assert version["curriculum_topics"][0]["id"] == "lo2024:III.4"
    (used,) = detail["usage"]
    assert (used["title"], used["class_name"], used["average"]) == (
        "Funkcja kwadratowa",
        "2C",
        0.72,
    )


def test_usage_keeps_a_class_whose_assignment_is_gone_without_an_average():
    detail = web().get(f"/api/bank/items/{uuid.UUID(int=1003)}").json()

    assert [(u["title"], u["class_name"], u["average"]) for u in detail["usage"]] == [
        ("Wzory skróconego mnożenia", "1A", 0.4),
        (None, "3B", None),
    ]


def test_an_unknown_item_is_not_found():
    client = web()
    gone = uuid.uuid4()

    assert client.get(f"/api/bank/items/{gone}").status_code == 404
    assert client.patch(f"/api/bank/items/{gone}", json={"text": "x"}).status_code == 404
    assert client.post(f"/api/bank/items/{gone}/retire").status_code == 404
    assert client.post(f"/api/bank/items/{gone}/restore").status_code == 404
    assert client.post(f"/api/bank/items/{gone}/dismiss-flag").status_code == 404


def test_an_edit_makes_a_new_version_and_the_ai_offers_a_new_solution():
    client = web()

    result = client.patch(
        f"/api/bank/items/{OPEN_ITEM}", json={"text": "Rozwiąż równanie $x^2 = 9$.", "points": 3}
    ).json()

    version = result["detail"]["item"]["version"]
    assert (version["number"], version["text"], version["points"]) == (
        2,
        "Rozwiąż równanie $x^2 = 9$.",
        3,
    )
    assert result["offer_regenerate"] is True
    assert client.get(f"/api/bank/items/{OPEN_ITEM}").json()["item"]["version"]["number"] == 2


def test_the_teacher_sets_topics_by_id_and_the_name_follows():
    result = web().patch(
        f"/api/bank/items/{OPEN_ITEM}",
        json={"curriculum_topic_ids": ["lo2024:II.1", "lo2024:III.1"], "difficulty": "hard"},
    )

    version = result.json()["detail"]["item"]["version"]
    assert [t["id"] for t in version["curriculum_topics"]] == ["lo2024:II.1", "lo2024:III.1"]
    assert version["curriculum_topics"][0]["name"].startswith("Stosuje wzory skróconego")
    assert version["difficulty"] == "hard"
    # Tags are not what the Model solution rests on.
    assert result.json()["offer_regenerate"] is False


def test_no_offer_when_the_teacher_wrote_the_solution_or_there_is_none():
    client = web()

    written = client.patch(
        f"/api/bank/items/{OPEN_ITEM}", json={"text": "Nowa treść.", "model_solution": "Nowe."}
    )
    closed = client.patch(f"/api/bank/items/{CLOSED_FLAGGED}", json={"text": "Nowa treść."})

    assert written.json()["offer_regenerate"] is False
    assert closed.json()["offer_regenerate"] is False


def test_an_edit_dismisses_the_flag():
    client = web()

    edited = client.patch(f"/api/bank/items/{CLOSED_FLAGGED}", json={"text": "Poprawione."})

    assert edited.json()["detail"]["item"]["flagged"] is False
    assert client.get("/api/home").json()["flagged_items"] == 3


def test_an_edit_the_item_would_not_hold_is_refused_and_changes_nothing():
    client = web()

    unfit = client.patch(f"/api/bank/items/{OPEN_ITEM}", json={"points": 1})
    unknown = client.patch(f"/api/bank/items/{OPEN_ITEM}", json={"curriculum_topic_ids": ["x"]})
    nothing = client.patch(f"/api/bank/items/{OPEN_ITEM}", json={})
    negative = client.patch(f"/api/bank/items/{OPEN_ITEM}", json={"points": -1})

    assert [r.status_code for r in (unfit, unknown, nothing, negative)] == [422] * 4
    assert "Rubric" in unfit.json()["detail"]
    assert client.get(f"/api/bank/items/{OPEN_ITEM}").json()["item"]["version"]["number"] == 1


def test_retire_and_restore_take_an_item_out_of_the_search_and_back():
    client = web()

    retired = client.post(f"/api/bank/items/{OPEN_ITEM}/retire").json()
    assert retired["item"]["retired"] is True
    assert len(found(client)) == 6
    restored = client.post(f"/api/bank/items/{RETIRED}/restore").json()

    assert restored["item"]["retired"] is False
    assert len(found(client)) == 7


def test_dismissing_a_flag_leaves_the_item_and_lowers_the_sidebar_count():
    client = web()
    assert client.get("/api/home").json()["flagged_items"] == 4

    dismissed = client.post(f"/api/bank/items/{CLOSED_FLAGGED}/dismiss-flag").json()

    assert dismissed["item"]["flagged"] is False
    assert dismissed["item"]["flag_reason"] is None
    assert dismissed["item"]["version"]["number"] == 1
    assert client.get("/api/home").json()["flagged_items"] == 3
