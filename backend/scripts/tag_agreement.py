"""Tags Exemplars with Jev and reports agreement with the tags they came with, per question.

    uv run python scripts/tag_agreement.py [FILE.jsonl] [--limit N]

FILE defaults to the invented fixtures (evals/tagging/fixtures.jsonl). A row has `id`, `text`,
`topics` (lo2024 topic IDs), `requirement` (I-IV) and `difficulty` (easy, medium, hard). For
local ZPE rows, map ZPE's tags to the same fields first. Only the numbers are printed, never
text, so the output can be posted on the issue.
"""

import argparse
import asyncio
import json
from pathlib import Path

from classlop.items.tagging import default_tagger

FIXTURES = Path(__file__).parent.parent / "evals/tagging/fixtures.jsonl"
LEVELS = ["easy", "medium", "hard"]


def section(topic_id: str) -> str:
    return topic_id.split(".")[0]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", type=Path, default=FIXTURES)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.file.read_text("utf-8").splitlines() if line]
    rows = rows[: args.limit]
    tagger = default_tagger()
    gate = asyncio.Semaphore(4)

    async def tag(row):
        async with gate:
            return await tagger.tag(row["text"])

    tagged = await asyncio.gather(*(tag(r) for r in rows))
    hits = {
        "section": 0,
        "topic_any": 0,
        "topic_exact": 0,
        "requirement": 0,
        "difficulty": 0,
        "difficulty_within_one": 0,
    }
    for row, tags in zip(rows, tagged, strict=True):
        want, got = set(row["topics"]), {t.id for t in tags.curriculum_topics}
        hits["section"] += {section(t) for t in want} == {section(t) for t in got}
        hits["topic_any"] += bool(want & got)
        hits["topic_exact"] += want == got
        hits["requirement"] += row["requirement"] in tags.general_requirements
        gap = abs(LEVELS.index(row["difficulty"]) - LEVELS.index(tags.difficulty))
        hits["difficulty"] += gap == 0
        hits["difficulty_within_one"] += gap <= 1
    print(f"n={len(rows)}")
    for name, count in hits.items():
        print(f"{name}: {count}/{len(rows)} = {count / len(rows):.0%}")


if __name__ == "__main__":
    asyncio.run(main())
