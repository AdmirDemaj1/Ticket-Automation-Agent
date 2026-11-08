# Meeting-to-Jira

Turn a recorded meeting into reviewed Jira sprint tickets. A user connects Jira, a code host and a transcript source, starts a run, reviews what the agent drafted, and approves before anything is written to Jira.

The full build spec is in [Claude-Reference.md](Claude-Reference.md). Design decisions are in [docs/DECISIONS.md](docs/DECISIONS.md), the security checklist in [docs/SECURITY.md](docs/SECURITY.md).

## Status

| Milestone | State |
|---|---|
| M0 Skeleton (monorepo, Compose, CI, healthchecks) | Done |
| M1 Auth + token vault | Done |
| M2 to M6 | Not started |

## Layout

```
apps/web        React 18 + Vite + Tailwind (shadcn/ui-style components)
apps/api        NestJS 11 + Prisma (public API, auth, token vault)
apps/agent      Python 3.12 + FastAPI (+ LangGraph from M2), internal only
packages/contracts   shared zod schemas for API bodies
infra/          docker-compose.yml, .env.example, local service config
docs/           DECISIONS.md, SECURITY.md
```

## Run it locally

Requirements: Docker, Node >= 20.19 with pnpm 10, Python 3.12 with [uv](https://docs.astral.sh/uv/).

```bash
# 1. Create a local env file with random secrets
sed -e "s|^SERVICE_TOKEN=.*|SERVICE_TOKEN=$(openssl rand -hex 32)|" \
    -e "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" \
    -e "s|^TOKEN_ENC_KEY=.*|TOKEN_ENC_KEY=$(openssl rand -base64 32)|" \
    infra/.env.example > infra/.env

# 2. Start everything
docker compose -f infra/docker-compose.yml up -d --build

# 3. Check it
curl localhost:3000/healthz   # API   -> {"status":"ok","db":"ok"}
curl localhost:8000/healthz   # agent -> {"status":"ok"}
open http://localhost:5173    # web
```

Host ports (all bound to 127.0.0.1): web 5173, API 3000 (Swagger at `/docs`), agent 8000, Postgres 5433, Redis 6379, S3 9000.

## Develop

```bash
pnpm install                 # JS workspaces
(cd apps/agent && uv sync)   # Python

pnpm lint && pnpm typecheck && pnpm test     # web, api, contracts
pnpm --filter @mtj/api test:e2e              # needs Postgres from Compose (mtj_test DB)
(cd apps/agent && uv run ruff check . && uv run mypy app tests && uv run pytest)
```

To run the API outside Docker, export the variables from `infra/.env` with `DATABASE_URL=postgresql://mtj:mtj@localhost:5433/mtj`, then `pnpm --filter @mtj/api dev`. Run the web dev server with `pnpm --filter @mtj/web dev`.

## Known risks

- Third-party API availability and plan limits: Spinach API/MCP, Teams transcripts needing admin consent, Jira required custom fields.
- LLM code analysis can miss things in large repos. The UI presents it as a starting point with evidence, never as an audit.
- Meeting transcripts and source code are sensitive. Customers may need a data-processing agreement with the AI provider and recording consent from participants.
