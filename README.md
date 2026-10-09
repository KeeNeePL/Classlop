# Classlop

A daily dashboard for a mathematics teacher in a Polish liceum, built on the teacher's own Microsoft 365 tenant. Lessons run as Teams meetings and students only ever use Teams; Classlop works with Teams on their behalf, generates and assigns tasks, and uses AI to grade submissions (including handwritten work) while the teacher spot-checks.

## Status

Building. The product is charted in [Classlop: product vision and feature map](https://github.com/KeeNeePL/Classlop/issues/1) and the architecture in [Classlop: architecture](https://github.com/KeeNeePL/Classlop/issues/27); build tickets hang off the area tickets there.

## Stack

- Python backend in `backend/` (FastAPI, LangChain, LangGraph), managed with [uv](https://docs.astral.sh/uv/)
- Postgres, OpenSearch, SQS and S3; AWS in prod, docker compose stand-ins in dev
- Microsoft Graph / Teams

## Running locally

Copy `.env.example` to `.env`, then:

```sh
docker compose up --build        # http://localhost:8000/healthz
cd backend && uv sync && uv run pytest
```

New migration on your area's branch: `cd backend && uv run alembic revision -m "..." --head=<area>@head`.

If Windows blocks compiled packages (Smart App Control), run the tests in Linux instead:

```sh
docker run --rm -v "$PWD/backend:/src" -w /src -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
  ghcr.io/astral-sh/uv:0.12.23-python3.13-trixie-slim uv run pytest
```

## Demo tenant

The team develops against a Microsoft 365 demo tenant. To create it, or to rebuild it when the 30-day trial expires, run `bash scripts/setup-demo-tenant.sh` from Git Bash. It walks you through the portals and writes the `M365_*` values into your gitignored `.env`. Teacher and Student passwords live in that `.env` too; ask the tenant admin for them in a private message. The admin password never goes in the repo folder.

## Working with agents

This repo is set up for AI coding agents:

- `AGENTS.md`: project instructions (`CLAUDE.md` imports it)
- `.claude/skills/`: [Matt Pocock's skills](https://github.com/mattpocock/skills) (MIT, see `.claude/skills/LICENSE-mattpocock-skills`)
- `docs/agents/`: issue tracker, triage label and domain doc conventions the skills read
- `.mcp.json`: Playwright MCP server

## Privacy

This repository is public. Student data and textbook content are never committed; use invented examples in code, tests and issues.
