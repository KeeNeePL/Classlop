"""MathML to inline LaTeX, for the elements ZPE's e-materials use."""

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

OPERATORS = {
    "·": r"\cdot ",
    "⋅": r"\cdot ",
    "×": r"\times ",
    "÷": r"\div ",
    "−": "-",
    "≤": r"\le ",
    "≥": r"\ge ",
    "≠": r"\ne ",
    "≈": r"\approx ",
    "∈": r"\in ",
    "∉": r"\notin ",
    "∪": r"\cup ",
    "∩": r"\cap ",
    "∞": r"\infty ",
    "π": r"\pi ",
    "α": r"\alpha ",
    "β": r"\beta ",
    "°": r"^\circ ",
    "⇒": r"\Rightarrow ",
    "⇔": r"\Leftrightarrow ",
    "%": r"\%",
}


INVISIBLE = "⁡⁢⁣⁤"


def to_latex(mathml: str) -> str:
    return _node(BeautifulSoup(mathml, "html.parser")).strip()


def _args(node: Tag) -> list[str]:
    return [_node(c) for c in node.children if isinstance(c, Tag)]


def _group(latex: str) -> str:
    return latex if len(latex) == 1 else "{" + latex + "}"


def _node(node: Tag | NavigableString | BeautifulSoup) -> str:
    if isinstance(node, NavigableString):
        return "".join(OPERATORS.get(ch, ch) for ch in node.strip() if ch not in INVISIBLE)
    name = node.name
    args = _args(node) if isinstance(node, Tag) else []
    match name:
        case "mfrac":
            return rf"\frac{{{args[0]}}}{{{args[1]}}}"
        case "msup":
            return f"{_group(args[0])}^{{{args[1]}}}"
        case "msub":
            return f"{_group(args[0])}_{{{args[1]}}}"
        case "msubsup":
            return f"{_group(args[0])}_{{{args[1]}}}^{{{args[2]}}}"
        case "msqrt":
            return rf"\sqrt{{{''.join(args)}}}"
        case "mroot":
            return rf"\sqrt[{args[1]}]{{{args[0]}}}"
        case "mover":
            return rf"\overline{{{args[0]}}}" if args[1] in ("¯", "‾", "-") else args[0]
        case "mfenced":
            opening, closing = node.get("open", "("), node.get("close", ")")
            return f"{opening}{(node.get('separators') or ',')[0].join(args)}{closing}"
        case "mtext":
            return rf"\text{{{node.get_text()}}}"
        case "mtable":
            rows = [
                " & ".join(_node(cell) for cell in row.find_all("mtd", recursive=False))
                for row in node.find_all("mtr", recursive=False)
            ]
            return r"\begin{cases}" + r" \\ ".join(rows) + r"\end{cases}"
        case "mo" | "mi" | "mn":
            return _node(NavigableString(node.get_text()))
        case _:
            return "".join(_node(c) for c in node.children if isinstance(c, Tag | NavigableString))
