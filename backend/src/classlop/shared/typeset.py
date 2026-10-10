"""Documents of Polish text with inline LaTeX maths, typeset to PDF with Typst and mitex."""

import re
from dataclasses import dataclass
from pathlib import Path

import typst

# Vendored, so rendering never reaches the network.
PACKAGES = Path(__file__).parent / "typst"
PREAMBLE = """#import "@preview/mitex:0.2.7": mi
#set page(paper: "a4")
#set text(lang: "pl")
"""
_TOKEN = re.compile(r"\\(begin|end)\s*\{([^}]*)\}|\\.|[{}]", re.DOTALL)


class TypesetError(ValueError):
    def __init__(self, message: str, block: int | None = None):
        super().__init__(message)
        # The index of the failing block, when the input is to blame and not Typst itself.
        self.block = block


@dataclass(frozen=True)
class Heading:
    text: str


@dataclass(frozen=True)
class Paragraph:
    text: str


def render(document: list[Heading | Paragraph]) -> bytes:
    """PDF bytes; maths is inline LaTeX between `$...$`, and `\\$` is a literal dollar."""
    blocks = []
    for index, block in enumerate(document):
        try:
            markup = _markup(block.text)
        except TypesetError as exc:
            raise TypesetError(str(exc), block=index) from exc
        blocks.append(f"= {markup}" if isinstance(block, Heading) else markup)
    try:
        return typst.compile((PREAMBLE + "\n\n".join(blocks)).encode(), package_path=str(PACKAGES))
    except typst.TypstError as exc:
        raise TypesetError(str(exc)) from exc


def _markup(text: str) -> str:
    return "".join(
        f"#mi({_string(_checked(part))})" if maths else f"#{_string(part)}"
        for maths, part in _segments(text)
        if part
    )


def _segments(text: str) -> list[tuple[bool, str]]:
    """The text split into plain and maths parts, alternating."""
    segments, part, maths, i = [], "", False, 0
    while i < len(text):
        pair = text[i : i + 2]
        if pair[0] == "\\" and len(pair) == 2:
            part += "$" if pair == "\\$" and not maths else pair
            i += 2
            continue
        if pair[0] == "$":
            if maths and not part:
                raise TypesetError(
                    f"display maths $$ is not supported, only inline $...$, in: {text}"
                )
            segments.append((maths, part))
            part, maths = "", not maths
        else:
            part += pair[0]
        i += 1
    if maths:
        raise TypesetError(f"unclosed $ in: {text}")
    return [*segments, (False, part)]


def _checked(latex: str) -> str:
    # mitex silently closes unbalanced braces and environments, which would print wrong maths.
    depth, environments = 0, []
    for token in _TOKEN.finditer(latex):
        if token[1] == "begin":
            environments.append(token[2])
        elif token[1] == "end":
            if not environments:
                raise TypesetError(f"\\end{{{token[2]}}} without its \\begin in: {latex}")
            if (opened := environments.pop()) != token[2]:
                raise TypesetError(f"\\end{{{token[2]}}} closes \\begin{{{opened}}} in: {latex}")
        elif token[0] in ("{", "}"):
            depth += 1 if token[0] == "{" else -1
            if depth < 0:
                raise TypesetError(f"unmatched }} in: {latex}")
    if environments:
        raise TypesetError(f"\\begin{{{environments[-1]}}} is never closed in: {latex}")
    if depth:
        raise TypesetError(f"unclosed {{ in: {latex}")
    return latex


def _string(text: str) -> str:
    """A Typst string literal."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'
