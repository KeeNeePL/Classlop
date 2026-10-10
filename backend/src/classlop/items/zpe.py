"""Splits a ZPE e-material (the HTML inside its EPUB) into Exemplars: one per numbered exercise,
sub-parts together, with ZPE's hint left out and its answer and solution kept. Interactive
exercises and those that need a figure are dropped."""

import asyncio
import html
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel

from classlop.items.exemplars import Exemplar
from classlop.items.mathml import to_latex
from classlop.items.tagging import Tagger
from classlop.items.types import Tags

META_KEYS = ("title", "core_curriculum", "keywords")
KEPT = {"StaticExerciseAnswer": "answer", "StaticExerciseSolution": "solution"}
DROPPED = {"StaticExerciseHint"}
BLOCKS = ("p", "li", "div", "ol", "ul", "br", "section", "tr")


class RawExemplar(BaseModel):
    """An exercise as ZPE has it, before tagging."""

    id: str
    order: int
    level: int | None  # ZPE's own difficulty, 1 to 3
    text: str
    answer: str | None = None
    solution: str | None = None


def _attr(tag: Tag | None, name: str) -> str:
    return str(tag.get(name) or "") if tag else ""


def _inline_math(node: Tag | BeautifulSoup) -> None:
    for span in node.select("[data-editor-mathml]"):
        span.replace_with(f"${to_latex(html.unescape(_attr(span, 'data-editor-mathml')))}$")


def _text(node: Tag | BeautifulSoup) -> str:
    _inline_math(node)
    # The specifier spans carry editor settings (the level digit), the buttons reveal hints.
    for noise in node.select(
        "span:has(> [data-specifier-type]), span:has(> [data-specifier-resolvedby]), button"
    ):
        noise.decompose()
    for br in node.find_all(BLOCKS):
        br.insert_after("\n")
    for li in node.find_all("li"):
        li.insert_before("- ")
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in node.get_text().splitlines())
    return "\n".join(line for line in lines if line)


# Figures and tables need a picture; a bare img is a rendered formula the MathML already gives.
def _needs_more_than_text(node: Tag | BeautifulSoup) -> bool:
    return bool(node.select("[data-validable], figure, svg, table"))


def _fragments(pages: list[str]) -> dict[int, list[Tag]]:
    """The StaticExercise pieces by exercise number; the EPUB is cut into files wherever it
    grew too long, so one exercise may span several."""
    found: dict[int, list[Tag]] = {}
    for page in pages:
        for section in BeautifulSoup(page, "html.parser").select(
            'section[data-block-name="StaticExercise"]'
        ):
            if meta := section.select_one("[data-exercise-order]"):
                found.setdefault(int(_attr(meta, "data-exercise-order")), []).append(section)
    return found


def split_exercises(pages: list[str], material_id: str) -> list[RawExemplar]:
    """The pages are the EPUB's HTML files in reading order."""
    exemplars = []
    for order, fragments in _fragments(pages).items():
        whole = BeautifulSoup("".join(map(str, fragments)), "html.parser")
        parts: dict[str, str] = {}
        for block in whole.select("[data-block-name]"):
            if block.decomposed:  # inside a block already handled
                continue
            name = _attr(block, "data-block-name")
            if name in KEPT:
                parts[KEPT[name]] = _text(block.extract())
            elif name in DROPPED or "difficulty-picker" in (block.get("class") or []):
                block.decompose()
        for title in whole.select(".elearning_exercise__title"):
            title.decompose()
        _inline_math(whole)
        text = _text(whole)
        if text and not _needs_more_than_text(whole):
            level = _attr(whole.select_one("[data-exercise-level]"), "data-exercise-level")
            exemplars.append(
                RawExemplar(
                    id=f"zpe:{material_id}:{order}",
                    order=order,
                    level=int(level) if level else None,
                    text=text,
                    **parts,
                )
            )
    return exemplars


async def build_bundle(
    raw: Path,
    out: Path,
    tagger: Tagger,
    embed: Callable[[list[str]], Awaitable[list[list[float]]]],
    *,
    concurrency: int = 4,
) -> int:
    """Turn the scraped materials in `raw` (one directory each, with `meta.json` and the EPUB's
    HTML under `pages/`) into the bundle at `out`; returns the number of Exemplars."""
    found: list[tuple[RawExemplar, dict]] = []
    for material in sorted(p for p in raw.iterdir() if (p / "meta.json").exists()):
        meta = json.loads((material / "meta.json").read_text("utf-8"))
        pages = [p.read_text("utf-8") for p in sorted((material / "pages").glob("*.html"))]
        for e in split_exercises(pages, material.name):
            found.append(
                (
                    e,
                    {
                        "material": material.name,
                        "meta": {k: meta[k] for k in META_KEYS if k in meta},
                    },
                )
            )
    gate = asyncio.Semaphore(concurrency)

    async def tag(text: str) -> Tags:
        async with gate:
            return await tagger.tag(text)

    tags = await asyncio.gather(*(tag(e.text) for e, _ in found))
    vectors = await embed([e.text for e, _ in found])
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for (e, origin), t, vector in zip(found, tags, vectors, strict=True):
            exemplar = Exemplar(
                id=e.id,
                source=f"zpe:{origin['material']}",
                text=e.text,
                answer=e.answer,
                solution=e.solution,
                source_tags={"level": e.level} | origin["meta"],
                embedding=vector,
                difficulty=t.difficulty,
                curriculum_topics=t.curriculum_topics,
                general_requirements=t.general_requirements,
            )
            f.write(exemplar.model_dump_json() + "\n")
    return len(found)
