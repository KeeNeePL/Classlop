# Knowledge base bundle

A bundle is a JSONL file, one Exemplar per line (`classlop.items.exemplars.Exemplar`):

| field | |
| --- | --- |
| `id` | stable key; a re-load updates in place (`zpe:<material>:<exercise>`) |
| `source` | where it came from (`zpe:<material>`) |
| `text` | the exercise, all mathematics as inline LaTeX |
| `answer`, `solution` | the source's own, when it has them |
| `difficulty`, `curriculum_topics`, `general_requirements` | the tags, as on an Item |
| `source_tags` | the source's own tags (ZPE level 1-3, title, podstawa ids), kept for comparison |
| `embedding` | optional; the load embeds the lines that lack one |

`invented.jsonl` is an invented bundle of 28 Exemplars in 3 Curriculum sections, used by the tests
and for trying the load in docker compose:

    uv run classlop load-knowledge-base evals/knowledge-base/invented.jsonl

The real bundle is built from ZPE (`scripts/zpe_scrape.py`, then `scripts/build_knowledge_base.py`)
under the gitignored `/data/` and loads the same way. ZPE content never enters the repo.
