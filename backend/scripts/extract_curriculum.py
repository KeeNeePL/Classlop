"""Regenerate src/classlop/items/lo2024.json from the act.

    uv run python scripts/extract_curriculum.py [--refresh]

Downloads Dz.U. 2018 poz. 467 as worded by Dz.U. 2024 poz. 1019 (the regulation that restates
Zalacznik nr 1) from ISAP, cuts out the basic-level mathematics requirements and has the chat
model turn the formulas, which the PDF text layer mangles, into inline LaTeX. A topic whose PDF
text is unchanged keeps the wording already committed, so a rerun reproduces the file; --refresh
asks the model again.
"""

import argparse
import base64
import io
import json
import re
from pathlib import Path

import httpx
import pypdfium2 as pdfium
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

ACT_URL = "https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU20240001019/O/D20241019.pdf"
OUT = Path(__file__).parent.parent / "src/classlop/items/lo2024.json"
PDF = Path(__file__).parent.parent.parent / "data/isap/D20241019.pdf"
# ISAP refuses requests that do not look like a browser.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126",
    "Accept": "application/pdf,*/*",
    "Accept-Language": "pl,en;q=0.8",
}

ROMAN = r"(?:I{1,3}|IV|VI{0,3}|IX|XI{0,3}|XIII)"
PAGE_HEADER = re.compile(r"^Dziennik Ustaw .{1,3} \d+ .{1,3} Poz\. 1019\b.*$")
SECTION = re.compile(rf"^({ROMAN})\. (.+?)\.?$")
ITEM = re.compile(r"^(\d+)\) ")


def download() -> bytes:
    if not PDF.exists():
        PDF.parent.mkdir(parents=True, exist_ok=True)
        reply = httpx.get(ACT_URL, headers=HEADERS, follow_redirects=True, timeout=120)
        reply.raise_for_status()
        PDF.write_bytes(reply.content)
    return PDF.read_bytes()


def math_lines(doc: pdfium.PdfDocument) -> list[tuple[int, str]]:
    """(page, line) of the mathematics requirements, page headers and blank lines dropped."""
    lines = [
        (n, line.strip())
        for n, page in enumerate(doc)
        for line in page.get_textpage().get_text_range().splitlines()
    ]
    # Soft hyphens survive as U+FFFE at a line end.
    lines = [(n, line.removesuffix("￾")) for n, line in lines if line]
    lines = [(n, line) for n, line in lines if not PAGE_HEADER.match(line)]
    start = next(
        i
        for i, (_, line) in enumerate(lines)
        if line == "MATEMATYKA" and lines[i + 1][1].startswith("ZAKRES PODSTAWOWY I ROZSZERZONY")
    )
    end = next(
        i for i, (_, line) in enumerate(lines[start:], start) if line.startswith("Warunki i sposób")
    )
    return lines[start:end]


def parse(lines: list[tuple[int, str]]) -> tuple[list[dict], list[dict]]:
    """General requirements and sections with their basic-level topics, in the PDF's wording."""
    texts = [line for _, line in lines]
    goals = texts.index("Cele kształcenia – wymagania ogólne")
    detail = texts.index("Treści nauczania – wymagania szczegółowe")
    return _general(texts[goals + 1 : detail]), _sections(lines[detail + 1 :])


def _general(texts: list[str]) -> list[dict]:
    found: list[tuple[str, list[str]]] = []
    for line in texts:
        if m := re.match(rf"^({ROMAN})\. (.*)$", line):
            found.append((m[1], [m[2]]))
        else:
            found[-1][1].append(line)
    out = []
    for roman, parts in found:
        name, _, rest = " ".join(parts).partition(". ")
        out.append({"id": roman, "name": name.rstrip("."), "description": rest.strip()})
    assert [g["id"] for g in out] == ["I", "II", "III", "IV"], out
    return out


def _sections(lines: list[tuple[int, str]]) -> list[dict]:
    sections: list[dict] = []
    reading = False  # inside a basic-level paragraph
    for page, line in lines:
        if m := SECTION.match(line):
            sections.append({"roman": m[1], "name": m[2], "parts": []})
            reading = False
        elif line.startswith("Zakres podstawowy."):
            reading = True
            line = line.removeprefix("Zakres podstawowy.").strip().removeprefix("Uczeń").strip(": ")
            if line:
                sections[-1]["parts"].append((page, line))
        elif line.startswith("Zakres rozszerzony."):
            reading = False
        elif reading:
            sections[-1]["parts"].append((page, line))
    return [_topics(s) for s in sections]


def _topics(section: dict) -> dict:
    items: list[dict] = []
    for page, line in section["parts"]:
        if (m := ITEM.match(line)) and int(m[1]) == len(items) + 1:
            items.append({"pages": {page}, "parts": [line[m.end() :]]})
        elif items:
            items[-1]["pages"].add(page)
            items[-1]["parts"].append(line)
        else:  # a section whose basic level is one unnumbered requirement
            items.append({"pages": {page}, "parts": [line]})
    roman = section["roman"]
    topics = [
        {
            "id": f"lo2024:{roman}.{n}",
            "source": re.sub(r"\s+", " ", " ".join(i["parts"])).strip().rstrip(";."),
            "pages": sorted(i["pages"]),
        }
        for n, i in enumerate(items, 1)
    ]
    return {"id": f"lo2024:{roman}", "name": section["name"], "topics": topics}


class Requirement(BaseModel):
    id: str
    wording: str


class Rewritten(BaseModel):
    requirements: list[Requirement]


PROMPT = """\
You restore the wording of Polish mathematics curriculum requirements from a damaged PDF text
layer. The page images show the true text.

For each numbered requirement, return the Polish sentence exactly as printed, with every formula,
expression and symbol written as inline LaTeX between single dollar signs. Fix the damage: doubled
letters (x printed as xx), fractions and binomials split over lines, lost sub- and superscripts.
Keep the words, the sub-points a), b) and the order. Do not add, drop or paraphrase anything.
Write the Polish tg as \\operatorname{tg}. Start the sentence with a lowercase verb as printed; no
trailing full stop or semicolon.
The pages hold more requirements than you are given, among them extended-level ones; ignore
those. Return one entry, with the id in brackets as listed, for each requirement listed and for no
other."""


async def reword(section: dict, doc: pdfium.PdfDocument, todo: list[dict]) -> list[str]:
    from classlop.shared import llm

    pages = sorted({p for t in todo for p in t["pages"]})
    images = []
    for n in pages:
        jpeg = io.BytesIO()
        doc[n].render(scale=2).to_pil().convert("RGB").save(jpeg, "JPEG", quality=85)
        url = "data:image/jpeg;base64," + base64.b64encode(jpeg.getvalue()).decode()
        images.append({"type": "image_url", "image_url": {"url": url}})
    listed = "\n".join(f"[{_short(t)}] {t['source']}" for t in todo)
    text = f"Section {section['id']} {section['name']}. Damaged text:\n{listed}"
    reply = await llm.ask(
        "curriculum.latex",
        Rewritten,
        [SystemMessage(PROMPT), HumanMessage([{"type": "text", "text": text}, *images])],
    )
    said = {r.id.strip("[] ").removeprefix("lo2024:"): r.wording for r in reply.requirements}
    missing = [t["id"] for t in todo if _short(t) not in said]
    assert not missing, f"no wording for {missing}"
    return [said[_short(t)] for t in todo]


def _short(topic: dict) -> str:
    return topic["id"].removeprefix("lo2024:")


def capitalised(text: str) -> str:
    return text[:1].upper() + text[1:]


# What marks a requirement as holding a formula; the rest is plain Polish and kept as printed.
MATH = re.compile(r"[0-9=<>|°−⋅𝐀-𝟿]")


async def build(refresh: bool) -> dict:
    doc = pdfium.PdfDocument(download())
    general, sections = parse(math_lines(doc))
    known = {} if refresh or not OUT.exists() else _committed(json.loads(OUT.read_text("utf-8")))
    for section in sections:
        todo = [
            t
            for t in section["topics"]
            if MATH.search(t["source"]) and known.get(t["id"], {}).get("source") != t["source"]
        ]
        if todo:
            for topic, name in zip(todo, await reword(section, doc, todo), strict=True):
                topic["name"] = name.strip()
        section["topics"] = [_final(t, known) for t in section["topics"]]
    return {
        "act": "Dz.U. 2018 poz. 467 w brzmieniu Dz.U. 2024 poz. 1019, zał. nr 1, matematyka",
        "general_requirements": general,
        "sections": sections,
    }


def _final(topic: dict, known: dict[str, dict]) -> dict:
    """The topic as committed: the model's wording if it was asked, else the one kept from the
    last run, else the PDF's own."""
    name = topic.get("name")
    if name is None and MATH.search(topic["source"]):
        name = known[topic["id"]]["name"]
    return {
        "id": topic["id"],
        "name": capitalised(name or topic["source"]),
        "source": topic["source"],
    }


def _committed(data: dict) -> dict[str, dict]:
    return {t["id"]: t for s in data["sections"] for t in s["topics"]}


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    data = asyncio.run(build(parser.parse_args().refresh))
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {sum(len(s['topics']) for s in data['sections'])} topics")


if __name__ == "__main__":
    main()
