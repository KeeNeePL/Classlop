"""Splitting a ZPE e-material into Exemplars, on invented markup shaped like the real EPUB."""

import json
from html import escape

from classlop.items import CurriculumTopic, Tags
from classlop.items.exemplars import parse_bundle
from classlop.items.zpe import build_bundle, split_exercises


def math(mathml: str) -> str:
    source = escape(f"<math>{mathml}</math>")
    return f'<span role="math" data-editor-mathml="{source}"><mjx-container></mjx-container></span>'


def block(name: str, body: str) -> str:
    return f'<section data-block-name="{name}"><div>{body}</div></section>'


def exercise(order: int, level: int, body: str, *extra: str) -> str:
    return block(
        "StaticExercise",
        f'<div class="elearning_exercise" data-exercise-level="{level}" '
        f'data-exercise-order="{order}">'
        f'<div class="elearning_exercise__title">Ćwiczenie <span>{order}</span></div>'
        f'<div class="main-section-content">{body}</div>{"".join(extra)}</div>',
    )


def page(*exercises: str) -> str:
    return f"<html><body>{''.join(exercises)}</body></html>"


def test_an_exercise_becomes_an_exemplar_with_latex_answer_and_solution():
    fraction = math(
        "<mfrac><mn>1</mn><mn>2</mn></mfrac><mo>+</mo><msup><mi>x</mi><mn>2</mn></msup>"
    )
    html = page(
        exercise(
            4,
            3,
            f"<p>Oblicz {fraction}.</p>",
            block("StaticExerciseHint", "<p>Sprowadź do wspólnego mianownika.</p>"),
            block("StaticExerciseAnswer", f"<p>{math('<mn>7</mn>')}</p>"),
            block("StaticExerciseSolution", "<p>Dodajemy ułamki.</p>"),
        )
    )
    (e,) = split_exercises([html], "PABC")
    assert e.id == "zpe:PABC:4"
    assert e.text == r"Oblicz $\frac{1}{2}+x^{2}$."
    assert e.answer == "$7$"
    assert e.solution == "Dodajemy ułamki."
    assert e.level == 3


def test_sub_parts_stay_with_their_exercise():
    body = "<p>Rozwiąż:</p><ol><li>pierwsze</li><li>drugie</li></ol>"
    e, _ = split_exercises([page(exercise(1, 1, body), exercise(2, 1, "<p>Inne.</p>"))], "PABC")
    assert "pierwsze" in e.text and "drugie" in e.text
    assert "Inne" not in e.text


def test_figure_dependent_and_interactive_exercises_are_dropped():
    figure = '<figure><img src="wykres.png"/></figure>'
    interactive = (
        '<figure data-validable=""><span class="sr-only">Przeciągnij liczby</span></figure>'
    )
    html = page(
        exercise(1, 1, f"<p>Odczytaj z wykresu.</p>{figure}"),
        exercise(2, 1, f"<p>Uzupełnij.</p>{interactive}"),
        exercise(3, 1, f"<p>Policz {math('<mn>2</mn>')}.</p>"),
    )
    assert [e.id for e in split_exercises([html], "PABC")] == ["zpe:PABC:3"]


async def test_raw_materials_are_built_into_a_tagged_embedded_bundle(tmp_path):
    material = tmp_path / "PABC"
    (material / "pages").mkdir(parents=True)
    (material / "meta.json").write_text(
        json.dumps({"title": "Równania", "core_curriculum": [4148], "keywords": ["równania"]}),
        "utf-8",
    )
    (material / "pages" / "000.html").write_text(
        page(exercise(1, 2, "<p>Rozwiąż równanie $x=1$.</p>"), exercise(2, 1, "<p>Policz.</p>")),
        "utf-8",
    )

    class FakeTagger:
        async def tag(self, text: str) -> Tags:
            return Tags(
                difficulty="hard",
                curriculum_topics=[CurriculumTopic(id="lo2024:III.4", name="Równania kwadratowe")],
                general_requirements=["I"],
            )

    async def embed(texts: list[str]) -> list[list[float]]:
        return [[float(len(t))] for t in texts]

    out = tmp_path / "bundle.jsonl"
    assert await build_bundle(tmp_path, out, FakeTagger(), embed) == 2

    first, second = parse_bundle(out.read_bytes())
    assert first.id == "zpe:PABC:1" and first.source == "zpe:PABC"
    assert first.difficulty == "hard" and first.curriculum_topics[0].id == "lo2024:III.4"
    assert first.embedding == [float(len(first.text))]
    assert first.source_tags == {
        "level": 2,
        "title": "Równania",
        "core_curriculum": [4148],
        "keywords": ["równania"],
    }
    assert second.source_tags["level"] == 1
