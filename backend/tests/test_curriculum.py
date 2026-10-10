import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from classlop import items
from classlop.items import CurriculumTopic, Tags

SCRIPT = Path(__file__).parent.parent / "scripts/extract_curriculum.py"


def test_the_set_holds_every_section_with_its_topics():
    sections = items.curriculum()

    assert [s.id for s in sections] == [
        f"lo2024:{r}" for r in "I II III IV V VI VII VIII IX X XI XII XIII".split()
    ]
    assert sections[0].name == "Liczby rzeczywiste"
    assert all(s.topics for s in sections)
    assert all(t.id.startswith(f"{s.id}.") for s in sections for t in s.topics)
    assert len({t.id for s in sections for t in s.topics}) == 73


def test_a_topic_has_its_id_and_polish_wording():
    topics = {t.id: t.name for s in items.curriculum() for t in s.topics}

    assert topics["lo2024:III.4"] == "Rozwiązuje równania i nierówności kwadratowe"


def test_formulas_are_inline_latex_with_the_pdf_damage_gone():
    topics = {t.id: t.name for s in items.curriculum() for t in s.topics}

    assert "$" in topics["lo2024:IX.4"]
    assert all(t.count("$") % 2 == 0 for t in topics.values())
    assert not any("\U0001d465" <= c <= "\U0001d7ff" for t in topics.values() for c in t)


def test_the_four_general_requirements():
    assert [(g.id, g.name) for g in items.general_requirements()] == [
        ("I", "Sprawność rachunkowa"),
        ("II", "Wykorzystanie i tworzenie informacji"),
        ("III", "Wykorzystanie i interpretowanie reprezentacji"),
        ("IV", "Rozumowanie i argumentacja"),
    ]


def test_an_unknown_topic_id_is_rejected():
    with pytest.raises(ValidationError, match="not a Curriculum topic"):
        CurriculumTopic(id="lo2024:II.5", name="Równania kwadratowe")  # II has four topics
    with pytest.raises(ValidationError):
        Tags(
            difficulty="easy",
            curriculum_topics=[{"id": "topic-x", "name": "x"}],  # pyright: ignore[reportArgumentType]
            general_requirements=["I"],
        )


def test_the_script_parses_a_requirement_run_of_the_act():
    spec = importlib.util.spec_from_file_location("extract_curriculum", SCRIPT)
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    lines = [
        (0, "Treści nauczania – wymagania szczegółowe"),
        (0, "VI. Ciągi."),
        (0, "Zakres podstawowy. Uczeń:"),
        (0, "1) oblicza wyrazy;"),
        (1, "2) sprawdza, czy ciąg"),
        (1, "jest arytmetyczny;"),
        (1, "Zakres rozszerzony. Uczeń spełnia wymagania, a ponadto:"),
        (1, "1) coś więcej."),
    ]

    sections = script._sections(lines[1:])

    assert [(t["id"], t["source"]) for t in sections[0]["topics"]] == [
        ("lo2024:VI.1", "oblicza wyrazy"),
        ("lo2024:VI.2", "sprawdza, czy ciąg jest arytmetyczny"),
    ]
