# Classlop

A daily dashboard for a mathematics teacher in a Polish school, built on the teacher's own Microsoft 365 tenant. Lessons run as Teams meetings and students only ever use Teams; Classlop works with Teams on their behalf, generates and assigns tasks, and uses AI to grade submissions (including handwritten work) while the teacher spot-checks.

## Status

Charting. There is no code yet. The product vision, settled decisions and open questions live in the map issue: [Classlop: product vision and feature map](https://github.com/KeeNeePL/Classlop/issues/1).

## Stack

- Python, managed with [uv](https://docs.astral.sh/uv/)
- LangChain and LangGraph
- Microsoft Graph / Teams

## Working with agents

This repo is set up for AI coding agents:

- `AGENTS.md`: project instructions (`CLAUDE.md` imports it)
- `.claude/skills/`: [Matt Pocock's skills](https://github.com/mattpocock/skills) (MIT, see `.claude/skills/LICENSE-mattpocock-skills`)
- `docs/agents/`: issue tracker, triage label and domain doc conventions the skills read
- `.mcp.json`: Playwright MCP server

## Privacy

This repository is public. Student data and textbook content are never committed; use invented examples in code, tests and issues.
