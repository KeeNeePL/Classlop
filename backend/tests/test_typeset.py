import re

import pypdfium2 as pdfium
import pytest

from classlop.shared.typeset import Heading, Paragraph, TypesetError, render


def text_of(pdf: bytes) -> str:
    document = pdfium.PdfDocument(pdf)
    return "\n".join(page.get_textpage().get_text_range() for page in document)


def test_polish_text_with_inline_latex_becomes_a_pdf():
    pdf = render(
        [
            Heading("Zadanie 3"),
            Paragraph(r"W kroku 2 pojawia się błąd: $\sqrt{\Delta} = \frac{36}{2}$, a nie $6^2$."),
            Paragraph(r"Układ $\begin{cases} x + y = 2 \\ x - y = 0 \end{cases}$ ma rozwiązanie."),
        ]
    )

    assert pdf.startswith(b"%PDF")
    text = text_of(pdf)
    assert "Zadanie 3" in text
    assert "W kroku 2 pojawia się błąd:" in text
    assert "ma rozwiązanie." in text


def test_text_outside_maths_is_printed_as_written():
    text = text_of(render([Paragraph('Zadanie *1* #2 _a_ [b] @c <d> 50% ~ / \\ "cytat"')]))

    assert 'Zadanie *1* #2 _a_ [b] @c <d> 50% ~ / \\ "cytat"' in text


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (r"Wynik $\frac{1}{2$.", "{"),
        (r"Wynik $\frac{1}}{2}$.", "}"),
        (r"$\begin{cases} x = 1$", r"\begin{cases}"),
        (r"$\begin{cases} x = 1 \end{array}$", r"\end{array}"),
        (r"Koszt $5 zł.", "$"),
    ],
)
def test_unbalanced_latex_is_refused_with_the_problem_named(text, problem):
    with pytest.raises(TypesetError, match=re.escape(problem)):
        render([Paragraph(text)])


def test_escaped_braces_and_dollars_are_not_counted():
    pdf = render([Paragraph(r"Zbiór $\{1, 2\}$ kosztuje 5\$.")])

    assert "kosztuje 5$." in text_of(pdf)


def test_display_maths_is_refused_rather_than_printed_as_text():
    with pytest.raises(TypesetError, match=re.escape("$$")):
        render([Paragraph("Wynik $$x^2$$ jest dodatni.")])


def test_the_error_names_the_failing_block():
    with pytest.raises(TypesetError) as error:
        render([Heading("Zadanie 1"), Paragraph("Dobrze."), Paragraph(r"Źle: $\frac{1}{2$")])

    assert error.value.block == 2


def test_mismatched_environments_name_both():
    with pytest.raises(TypesetError, match=re.escape(r"\end{array} closes \begin{cases}")):
        render([Paragraph(r"$\begin{cases} x \end{array}$")])


def test_an_environment_written_with_a_space_is_still_checked():
    with pytest.raises(TypesetError, match="cases"):
        render([Paragraph(r"$\begin {cases} x = 1$")])
