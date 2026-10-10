"""Step 1 of the Knowledge base: downloads ZPE's liceum mathematics e-materials into the
gitignored /data/zpe/, one directory per material:

    uv run python scripts/zpe_scrape.py [--out DIR] [--delay SECONDS] [--limit N]

ZPE serves a JSON search API (zpe.gov.pl/api/v1/search) and each material as an EPUB
(zpe.gov.pl/package/epub/<id>), whose HTML is saved under `pages/`. `meta.json` keeps ZPE's own
tags: the title and the Core curriculum (podstawa) ids, found by searching once per id. Basic level
only: materials whose title matches --skip-title (default "rozszerz") are left out. Re-running
skips what is already downloaded.
"""

import argparse
import io
import json
import re
import time
import zipfile
from pathlib import Path

import httpx

API = "https://zpe.gov.pl/api/v1"
LICEUM_MATHEMATICS = {"filter[stage][]": "E4", "filter[subject][]": "23"}
USER_AGENT = "Classlop-knowledge-base/0.1 (teacher tool; throttled)"
PAGE = 100


class Throttled:
    def __init__(self, delay: float):
        self.delay, self.last = delay, 0.0
        self.http = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
        )

    def get(self, url: str, **params) -> httpx.Response:
        time.sleep(max(0.0, self.last + self.delay - time.monotonic()))
        response = self.http.get(url, params=params)
        self.last = time.monotonic()
        response.raise_for_status()
        return response


def search(zpe: Throttled, **extra) -> list[dict]:
    base = {"searcher": "main", "filter[isStudentContent]": "true", "filter[language][]": "pl"}
    found, page = [], 1
    while True:
        data = zpe.get(
            f"{API}/search",
            **base,
            **LICEUM_MATHEMATICS,
            **extra,
            perPage=PAGE,
            page=page,
            format="json",
        ).json()["data"]
        found += data
        if len(data) < PAGE:
            return found
        page += 1


def core_curriculum_ids(zpe: Throttled) -> list[str]:
    filters = json.dumps({"stage": ["E4"], "subject": [23]})
    counts = zpe.get(f"{API}/search-counts", searcher="main", query="", filterJson=filters).json()
    return list(counts["coreCurriculum"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).parents[2] / "data/zpe")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-title", default="rozszerz")
    args = parser.parse_args()
    zpe = Throttled(args.delay)

    materials = {m["id"]: m for m in search(zpe)}
    podstawa: dict[str, list[int]] = {}
    for cid in core_curriculum_ids(zpe):
        for m in search(zpe, **{"filter[coreCurriculum][]": cid}):
            podstawa.setdefault(m["id"], []).append(int(cid))
    chosen = [m for m in materials.values() if not re.search(args.skip_title, m["title"], re.I)]
    for material in chosen[: args.limit]:
        folder = args.out / material["id"]
        if (folder / "meta.json").exists():
            continue
        epub = zpe.get(f"https://zpe.gov.pl/package/epub/{material['id']}").content
        with zipfile.ZipFile(io.BytesIO(epub)) as z:
            (folder / "pages").mkdir(parents=True, exist_ok=True)
            names = sorted(n for n in z.namelist() if n.endswith(".html") and "tree" not in n)
            for n, name in enumerate(names):
                (folder / "pages" / f"{n:03}.html").write_bytes(z.read(name))
        meta = {
            "title": material["title"],
            "core_curriculum": sorted(podstawa.get(material["id"], [])),
            "keywords": material["tags"],
        }
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
        print(material["id"], material["title"])


if __name__ == "__main__":
    main()
