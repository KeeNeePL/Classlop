# Classlop

A daily dashboard for one mathematics teacher in a Polish liceum, built on the teacher's own Microsoft 365 tenant. The teacher is a persona the team speaks for; the team runs a demo tenant. Lessons are online Teams meetings; students only ever use Teams, and Classlop talks to Teams on their behalf. AI grades every submission and the teacher spot-checks.

**Phase: charting.** Issue #1 (`gh issue view 1 --json body`) is the product map and the single source of truth for scope, settled decisions, open questions and out-of-scope items. Read it before proposing anything.

## Stack

Python backend (FastAPI, LangChain, LangGraph) and an Angular frontend; prod on AWS, dev on local stand-ins through docker compose. The system shape and seams are in the resolution of issue #28 and in `docs/adr/`. Run all Python through uv: `uv run` for scripts and tools, `uv add` / `uv remove` for dependencies, `uv sync` to install. Never call `python`, `pip` or `python -m` directly.

## Code style

- Concise: the shortest clear solution.
- Comment only where the code cannot say why.
- No emoji anywhere.

## Vocabulary

Use the terms in `GLOSSARY.md`. A *Class* is the group of students, never the meeting. `domain-modeling` owns `GLOSSARY.md`; create it when the first term settles.

## Privacy

This repo is public. Use invented examples everywhere; student data and textbook content stay out of commits, issues and PRs.

### Issue tracker

GitHub Issues on `KeeNeePL/Classlop`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Shipping an issue

Ship each completed issue as a PR: commit on a new branch `<issue-number>-<short-slug>` cut from `main`, push it, and open the PR with `gh pr create`, its body carrying `Closes #<issue-number>` so merging closes the issue.

### Triage labels

The five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Tests

Running the backend tests (the working command, the per-run database, background processes): `docs/agents/testing.md`.
