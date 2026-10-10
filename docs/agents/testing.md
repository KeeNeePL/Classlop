# Running the tests

Backend tests run from `backend/` against the compose stand-ins:

```
docker compose up -d postgres elasticmq s3 opensearch
uv run python -m pytest
```

- On Windows `uv run pytest` can be blocked by Windows Application Control; `uv run python -m pytest` is the same run.
- `tests/conftest.py` gives each run a private Postgres database, created before the first test and dropped after the last. Another branch's migrations, a parallel run or the dev database never meet yours; there is no scratch database to set up.
- A full run takes about 2 minutes. Run it as one foreground command and leave nothing running in the background afterwards: a lingering shell wakes a finished subagent over and over.
- `live` tests need the demo tenant and are deselected by default: `uv run python -m pytest -m live`.
- Lint before reporting done: `uv run ruff check .` and `uv run ruff format --check .`.
