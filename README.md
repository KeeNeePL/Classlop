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

## Deploying to AWS

One `Classlop` stack in eu-central-1, deployed by hand from `main` into the hackathon account. It needs Docker running (the image is built during deploy), the AWS CLI signed in to that account, and Node for the CDK CLI.

```sh
cd infra
# Once per account: OpenSearch in a VPC needs its service-linked role; an error saying it exists is fine.
aws iam create-service-linked-role --aws-service-name opensearchservice.amazonaws.com
npx --yes aws-cdk@2.1145.0 bootstrap aws://<account-id>/eu-central-1   # once per account
npx --yes aws-cdk@2.1145.0 deploy Classlop
```

The deploy prints `Url` (the dashboard on `*.cloudfront.net`) and `CallbackUrl`. The stack runs at about 4 USD a day; the account's own 25 USD monthly AWS Budget is the cost alarm, so the stack adds none.

**Fill the app secret** `classlop/app` once, in the Secrets Manager console (Retrieve secret value, Edit, key/value): `M365_CLIENT_SECRET`, `LLM_API_KEY`, `LANGSMITH_API_KEY`, `TYPESAFE_API_KEY`, `LLM_BASE_URL`, `M365_TENANT_ID`, `M365_CLIENT_ID`. `SESSION_KEY` is generated; leave it. Later deploys never overwrite these values. The tasks read the secret when they start, so restart both services after an edit:

```sh
aws ecs update-service --cluster <ClusterName> --service <service> --force-new-deployment
```

**Add the CloudFront redirect** once: in the Entra portal, app registration "Classlop dev", Authentication, add `CallbackUrl` as a Web redirect URI.

**Run a one-off job** such as the `ping` round-trip through the queue and the worker, with the stack outputs:

```sh
aws ecs run-task --cluster <ClusterName> --task-definition <WorkerTaskDefinition> --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<PublicSubnets>],securityGroups=[<TasksSecurityGroup>],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"worker","command":["classlop","ping"]}]}'
```

**Tear everything down** after the hackathon: `bash scripts/teardown.sh` destroys the stack, force-deletes the secrets, removes leftover Lambda log groups and asks before removing the CDK bootstrap stack.

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
