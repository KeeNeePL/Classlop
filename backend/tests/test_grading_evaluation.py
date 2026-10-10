"""The evaluation report, worked out by hand for two graded Submissions."""

from classlop.grading.evaluation import metrics

REFERENCES = [
    {
        "held": True,
        "items": [
            {"number": 1, "format": "closed", "points": 1, "reading": "readable", "leaks": []},
            {"number": 2, "format": "open", "points": 2, "reading": "unsure", "leaks": ["x_2 = 5"]},
        ],
    },
    {
        "held": False,
        "items": [
            {"number": 1, "format": "closed", "points": 0, "reading": "readable", "leaks": []},
            {
                "number": 2,
                "format": "open",
                "points": 1,
                "reading": "readable",
                "leaks": [r"h = \frac{24}{5}"],
            },
        ],
    },
]


def graded(number, points, reading, feedback) -> dict:
    return {"number": number, "points": points, "reading": reading, "feedback": feedback}


OUTPUTS = [
    {
        "held": True,
        "summary": "Zadanie 2 wymaga dokończenia.",
        "items": [
            graded(1, 1, "readable", "poprawnie"),
            # Wrong points, and the final answer given away despite the spacing.
            graded(2, 1, "unsure", "Brakuje drugiego pierwiastka $x_2=5$."),
        ],
    },
    {
        "held": True,
        "summary": r"Wynik to $h = \dfrac{24}{5}$.",
        "items": [
            graded(1, 0, "readable", "błędna odpowiedź"),
            graded(2, 1, "unsure", "W kroku 2..."),
        ],
    },
]


def test_the_report_compares_every_item_and_the_held_decision():
    assert metrics(OUTPUTS, REFERENCES) == {
        "submissions": 2,
        "items": 4,
        "held_expected": 1,
        "held_graded": 2,
        "points_agreement": 0.75,
        "points_agreement_closed": 1.0,
        "points_agreement_open": 0.5,
        "reading_agreement": 0.75,
        "held_recall": 1.0,
        "held_precision": 0.5,
        "feedback_leaks": 1,
        "summary_leaks": 1,
    }


def test_an_item_missing_from_the_result_disagrees():
    output = {"held": False, "summary": "", "items": []}

    report = metrics([output], REFERENCES[1:])

    assert (report["points_agreement"], report["reading_agreement"]) == (0.0, 0.0)
    # Nothing was Held, so there is no precision to report.
    assert (report["held_recall"], report["held_precision"]) == (None, None)


def test_a_leak_is_the_whole_number_not_a_part_of_one():
    output = {
        "held": False,
        "summary": "",
        "items": [
            graded(1, 0, "readable", "błędna odpowiedź"),
            graded(2, 1, "readable", "Sprawdź, czy $x_2=50$ spełnia równanie."),
        ],
    }
    reference = {**REFERENCES[1], "items": [REFERENCES[1]["items"][0], REFERENCES[0]["items"][1]]}

    assert metrics([output], [reference])["feedback_leaks"] == 0
