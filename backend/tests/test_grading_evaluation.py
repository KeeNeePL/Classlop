"""The evaluation report, worked out by hand for two graded Submissions."""

from classlop.grading.evaluation import metrics

REFERENCES = [
    {
        "held": True,
        "items": [
            {
                "number": 1,
                "format": "closed",
                "points": 1,
                "reading": "readable",
                "leaks": [],
                "transcription": "B",
            },
            {
                "number": 2,
                "format": "open",
                "points": 2,
                "reading": "unsure",
                "leaks": ["x_2 = 5"],
                "transcription": "x_1 = -1",
            },
        ],
    },
    {
        "held": False,
        "items": [
            {
                "number": 1,
                "format": "closed",
                "points": 0,
                "reading": "readable",
                "leaks": [],
                "transcription": "C",
            },
            {
                "number": 2,
                "format": "open",
                "points": 1,
                "reading": "readable",
                "leaks": [r"h = \frac{24}{5}"],
                "transcription": "P = 24\n[rysunek: trójkąt prostokątny]",
            },
        ],
    },
]


def graded(number, points, reading, feedback, transcription="", disputed=False) -> dict:
    return {
        "number": number,
        "points": points,
        "reading": reading,
        "feedback": feedback,
        "transcription": transcription,
        "disputed": disputed,
    }


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
        "held_false": 1,
        "held_false_dispute_correct_transcription": 0,
        "held_false_dispute_wrong_transcription": 0,
        "held_false_unsure_transcription": 1,
        "held_false_other": 0,
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


def test_false_held_is_broken_down_by_cause():
    def held(item: dict) -> dict:
        return {"held": True, "summary": "", "items": [graded(1, 0, "readable", "", "C"), item]}

    outputs = [
        # The spacing and a drawing's description need not match word for word.
        held(graded(2, 1, "unsure", "", "P=24\n[rysunek: trójkąt]", disputed=True)),
        held(graded(2, 1, "unsure", "", "P = 42", disputed=True)),
        held(graded(2, 1, "unsure", "", "P = 24")),
        # Failed to grade: Held with no Items.
        {"held": True, "summary": "", "items": []},
    ]

    report = metrics(outputs, REFERENCES[1:] * 4)

    assert report["held_false"] == 4
    assert [
        report["held_false_dispute_correct_transcription"],
        report["held_false_dispute_wrong_transcription"],
        report["held_false_unsure_transcription"],
        report["held_false_other"],
    ] == [1, 1, 1, 1]
