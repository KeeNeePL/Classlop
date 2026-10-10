# /// script
# requires-python = ">=3.13"
# dependencies = ["openai>=2", "python-dotenv>=1"]
# ///
"""PROTOTYPE, throw away. Can the configured chat model read and grade set-01?

One call per Submission: all pages plus the Items in, per-Item reading and points out.
Compares with expected.json. Run from the repo root:
    uv run backend/evals/grading/prototype_read_check.py
"""

import base64
import json
import os
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(".env")
SET = pathlib.Path("backend/evals/grading/set-01")
ITEMS = json.loads((SET / "items.json").read_text(encoding="utf-8"))["items"]
MODEL = json.loads(os.environ.get("LLM_MODELS") or "{}").get(
    "grading.transcribe", os.environ.get("LLM_CHAT_MODEL", "gpt-5.4-mini")
)
# The team endpoint is Azure API Management: it rejects Bearer and wants an api-key header.
client = OpenAI(
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ["LLM_API_KEY"],
    default_headers={"api-key": os.environ["LLM_API_KEY"]},
)

PROMPT = """You grade a Polish high-school maths test from photos of a student's handwritten pages.
Pages may be rotated; read them as they are. Items may be unnumbered or out of order: attribute work
to the Item whose task it copies; if work fits no single Item, mark that Item "unsure".

For each Item:
- transcription: verbatim LaTeX of the student's work for that Item, mistakes included, never corrected.
  Describe drawings and crossed-out parts in square brackets. For a closed Item give only the chosen
  option label; if the student wrote an option's value instead, give the label it matches. Empty if blank.
- reading: "readable", "unsure" (you are not certain what is written, e.g. 1 vs 7, or two options marked),
  "unreadable" (cannot be read at all), or "blank" (nothing written for this Item).
- drawing: true if the work for this Item contains a drawing.
- points: for open Items, whole points at the highest Rubric level the work reaches (any correct method
  counts); for closed Items, null. Blank or unreadable: 0.
- doubt: true if the work fits no Rubric level cleanly (e.g. a correct result after a wrong step).
Do not use outside knowledge of the answer for closed Items; just read the label."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["number", "transcription", "reading", "drawing", "points", "doubt"],
                "properties": {
                    "number": {"type": "integer"},
                    "transcription": {"type": "string"},
                    "reading": {"enum": ["readable", "unsure", "unreadable", "blank"]},
                    "drawing": {"type": "boolean"},
                    "points": {"type": ["integer", "null"]},
                    "doubt": {"type": "boolean"},
                },
            },
        }
    },
}


def items_for_model() -> str:
    shown = []
    for i in ITEMS:
        item = {k: i[k] for k in ("number", "format", "max_points", "text", "options")}
        if i["format"] == "open":
            item |= {"model_solution": i["model_solution"], "rubric": i["rubric"]}
        shown.append(item)
    return json.dumps(shown, ensure_ascii=False, indent=1)


def grade(submission: pathlib.Path) -> dict:
    pages = sorted(submission.glob("page-*.jpg"))
    images = [
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()
            },
        }
        for p in pages
    ]
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": [{"type": "text", "text": "Items:\n" + items_for_model()}, *images]},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "grading", "schema": SCHEMA, "strict": True},
        },
    )
    got = {i["number"]: i for i in json.loads(response.choices[0].message.content)["items"]}
    for i in ITEMS:
        g = got.setdefault(i["number"], {"transcription": "", "reading": "blank", "drawing": False, "points": 0, "doubt": False})
        if i["format"] == "closed":
            g["points"] = int(g["reading"] == "readable" and g["transcription"].strip().upper() == i["answer"])
        if g["reading"] in ("blank", "unreadable"):
            g["points"] = 0
    return {"got": got, "usage": response.usage.total_tokens if response.usage else None}


def held(items: dict) -> bool:
    return any(i["reading"] in ("unsure", "unreadable") or i.get("doubt") for i in items.values())


subs = sorted(p for p in (SET / "submissions").iterdir() if p.is_dir())
print(f"model: {MODEL}, submissions: {len(subs)}\n")
with ThreadPoolExecutor(8) as pool:
    results = dict(zip(subs, pool.map(grade, subs)))

point_hits = point_total = read_hits = held_hits = 0
for sub, result in results.items():
    exp = json.loads((sub / "expected.json").read_text(encoding="utf-8"))
    expected = {i["number"]: i for i in exp["items"]}
    got = result["got"]
    print(f"== {sub.name}  tokens={result['usage']}")
    print(f"   {'Zad':>3} {'exp pts':>7} {'got pts':>7} {'exp read':>10} {'got read':>10} {'doubt e/g':>9}")
    for n in sorted(expected):
        e, g = expected[n], got[n]
        point_total += 1
        point_hits += e["points"] == g["points"]
        read_hits += e["reading"] == g["reading"]
        mark = "" if e["points"] == g["points"] and e["reading"] == g["reading"] else "  <--"
        print(
            f"   {n:>3} {e['points']:>7} {g['points']:>7} {e['reading']:>10} {g['reading']:>10}"
            f" {str(e.get('doubt', False))[0]}/{str(g['doubt'])[0]:>7}{mark}"
        )
    h = held(got)
    held_hits += h == exp["held"]
    print(
        f"   total exp {sum(i['points'] for i in expected.values())} got {sum(g['points'] for g in got.values())}"
        f" | held exp {exp['held']} got {h}"
        f" | drawing got {any(g['drawing'] for g in got.values())}"
    )
    for n in (1, 3):
        print(f"   zad {n} transcription: {got[n]['transcription']!r}")
    print()

print(f"points agreement {point_hits}/{point_total}, reading agreement {read_hits}/{point_total}, held agreement {held_hits}/{len(subs)}")
out = pathlib.Path(os.environ.get("TEMP", ".")) / "classlop_read_check.json"
out.write_text(json.dumps({s.name: r for s, r in results.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"full output: {out}")
