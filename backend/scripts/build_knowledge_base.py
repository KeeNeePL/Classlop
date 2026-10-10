"""Step 2 of the Knowledge base: splits the scraped materials into Exemplars, tags them with Jev,
embeds them and writes the bundle (JSONL with embeddings).

    uv run python scripts/build_knowledge_base.py [--raw DIR] [--out FILE]

Then `uv run classlop load-knowledge-base FILE` uploads it and queues the load.
"""

import argparse
import asyncio
from pathlib import Path

from classlop.items import embedding
from classlop.items.tagging import default_tagger
from classlop.items.zpe import build_bundle

DATA = Path(__file__).parents[2] / "data"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=DATA / "zpe")
    parser.add_argument("--out", type=Path, default=DATA / "knowledge-base.jsonl")
    args = parser.parse_args()
    count = await build_bundle(args.raw, args.out, default_tagger(), embedding.embed)
    print(f"{count} Exemplars -> {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
