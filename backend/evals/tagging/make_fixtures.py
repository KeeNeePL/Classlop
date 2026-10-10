# ruff: noqa: E501
"""Writes fixtures.jsonl: invented Exemplars with the tags the team expects (id, text, topics,
requirement, difficulty). Run: uv run python evals/tagging/make_fixtures.py"""

import json
from pathlib import Path

R = [
    ("lo2024:III.3", "I", "easy", r"Rozwiąż nierówność $3x - 5 < 10$."),
    (
        "lo2024:III.3",
        "I",
        "medium",
        r"Rozwiąż nierówność $\frac{2x-1}{3} \ge \frac{x+4}{2}$ i podaj najmniejszą liczbę całkowitą spełniającą ją.",
    ),
    ("lo2024:III.4", "I", "easy", r"Rozwiąż równanie $x^2 - 9 = 0$."),
    ("lo2024:III.4", "I", "easy", r"Rozwiąż równanie $x^2 - 5x + 6 = 0$."),
    ("lo2024:III.4", "I", "medium", r"Rozwiąż nierówność $2x^2 - 3x - 5 \le 0$."),
    (
        "lo2024:III.4",
        "IV",
        "hard",
        r"Wyznacz wszystkie wartości parametru $m$, dla których równanie $x^2 - mx + m + 3 = 0$ ma dwa różne pierwiastki ujemne.",
    ),
    ("lo2024:III.5", "I", "medium", r"Rozwiąż równanie $x^3 - 4x = 0$."),
    (
        "lo2024:III.1",
        "II",
        "medium",
        r"Wyjaśnij, dlaczego równania $x + 2 = 5$ oraz $2x + 4 = 10$ są równoważne.",
    ),
    (
        "lo2024:III.2",
        "II",
        "easy",
        r"Ile rozwiązań ma równanie $2(x+1) = 2x + 3$? Uzasadnij odpowiedź.",
    ),
    (
        "lo2024:III.4",
        "III",
        "medium",
        r"Prostokątna działka ma obwód $40$ m i pole co najmniej $75$ m$^2$. Wyznacz możliwe długości krótszego boku.",
    ),
    ("lo2024:V.2", "I", "easy", r"Dla funkcji $f(x) = 3x - 7$ oblicz $f(4)$."),
    ("lo2024:V.2", "I", "easy", r"Dla funkcji $f(x) = x^2 + 2x$ oblicz $f(-3)$."),
    (
        "lo2024:V.4",
        "II",
        "easy",
        r"Z wykresu funkcji $f$ odczytaj jej miejsca zerowe i zbiór wartości.",
    ),
    (
        "lo2024:V.4",
        "II",
        "medium",
        r"Na rysunku przedstawiono wykres funkcji $f$ określonej w przedziale $\langle -4, 5 \rangle$. Podaj przedziały, w których funkcja jest malejąca.",
    ),
    (
        "lo2024:V.5",
        "II",
        "easy",
        r"Funkcja liniowa $f(x) = (m-2)x + 1$ jest rosnąca. Wyznacz możliwe wartości $m$.",
    ),
    (
        "lo2024:V.6",
        "I",
        "easy",
        r"Wyznacz wzór funkcji liniowej, której wykres przechodzi przez punkty $A=(0,1)$ i $B=(2,5)$.",
    ),
    (
        "lo2024:V.6",
        "I",
        "medium",
        r"Wykres funkcji liniowej jest równoległy do prostej $y = -2x + 3$ i przechodzi przez punkt $(1, 4)$. Wyznacz jej wzór.",
    ),
    (
        "lo2024:V.1",
        "III",
        "medium",
        r"Opisz słownie funkcję przyporządkowującą każdej liczbie naturalnej resztę z jej dzielenia przez $3$ i podaj jej zbiór wartości.",
    ),
    (
        "lo2024:V.2",
        "III",
        "hard",
        r"Funkcja $f$ dana jest wzorem $f(x) = \frac{ax+1}{x-2}$ i $f(3) = 7$. Oblicz $a$ i rozwiąż równanie $f(x) = 0$.",
    ),
    (
        "lo2024:V.3",
        "II",
        "medium",
        r"W tabeli podano temperaturę o różnych godzinach doby. Oblicz, o ile stopni średnio wzrosła temperatura między godziną $6$ a $12$.",
    ),
    (
        "lo2024:VI.1",
        "I",
        "easy",
        r"Ciąg $(a_n)$ jest określony wzorem $a_n = 2n - 3$. Oblicz $a_5$.",
    ),
    (
        "lo2024:VI.2",
        "I",
        "easy",
        r"Ciąg określono rekurencyjnie: $a_1 = 2$, $a_{n+1} = 3a_n - 1$. Oblicz $a_3$.",
    ),
    ("lo2024:VI.4", "II", "medium", r"Wykaż, że ciąg $a_n = 4n + 1$ jest arytmetyczny."),
    (
        "lo2024:VI.5",
        "I",
        "easy",
        r"Pierwszy wyraz ciągu arytmetycznego wynosi $3$, a różnica $2$. Oblicz $a_{10}$.",
    ),
    (
        "lo2024:VI.5",
        "I",
        "medium",
        r"Oblicz sumę dwudziestu początkowych wyrazów ciągu arytmetycznego, w którym $a_1 = 5$ i $a_{20} = 62$.",
    ),
    (
        "lo2024:VI.6",
        "I",
        "medium",
        r"W ciągu geometrycznym $a_1 = 2$ i $a_4 = 54$. Oblicz iloraz tego ciągu.",
    ),
    (
        "lo2024:VI.6",
        "III",
        "hard",
        r"Liczby $x$, $6$, $y$ tworzą ciąg arytmetyczny, a liczby $x$, $4$, $y - 3$ ciąg geometryczny. Wyznacz $x$ i $y$.",
    ),
    ("lo2024:VI.3", "II", "medium", r"Zbadaj monotoniczność ciągu $a_n = \frac{n}{n+1}$."),
    (
        "lo2024:VI.5",
        "III",
        "medium",
        r"Sala ma $12$ miejsc w pierwszym rzędzie, a każdy następny rząd ma o $2$ miejsca więcej. Ile miejsc jest w sali o $15$ rzędach?",
    ),
    (
        "lo2024:VI.6",
        "III",
        "medium",
        r"Wartość samochodu spada co roku o $15\%$. Po ilu latach jego wartość będzie mniejsza niż połowa początkowej?",
    ),
]
out = Path(__file__).parent / "fixtures.jsonl"
with out.open("w", encoding="utf-8") as f:
    for i, (topic, req, diff, text) in enumerate(R, 1):
        row = {
            "id": f"fx-{i:02d}",
            "text": text,
            "topics": [topic],
            "requirement": req,
            "difficulty": diff,
        }
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
