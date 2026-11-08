# Decisions

Decisions for v1 (single user, local). Each entry: what, why, when. `VERIFY` items from the spec are listed at the end with their status.

Specs: [Claude-Reference.md](../Claude-Reference.md) is the v1 spec. [AGENT_SPEC_meeting-to-jira.md](../AGENT_SPEC_meeting-to-jira.md) is the multi-user roadmap. Research on the third-party APIs is in [INTEGRATIONS.md](INTEGRATIONS.md).

## D1. v1 starts from a fresh branch; multi-user work is parked (2026-11-08, M1)

Milestones M0 and M1 of the multi-user spec (NestJS API, JWT auth, encrypted token vault, Postgres/Redis/S3, Docker Compose) are on branch `feat/foundation`. v1 does not use them. The branch stays as-is for the roadmap's multi-user step. v1 reuses the FastAPI skeleton and the React UI components from it.

## D2. Library versions (2026-11-08, M1)

Frontend keeps the majors chosen for the earlier work: React 18 (as the spec said), Vite 6, Vitest 3, TypeScript 5.9, Tailwind 4, ESLint 9. Newer majors exist (Vite 8, Vitest 5, TypeScript 7), but Vitest 5 and jsdom 27+ need Node 22 and the dev machine runs Node 20.19. Backend: Python 3.12, FastAPI, Pydantic 2, managed with `uv`.

## D3. UI components: shadcn/ui style, written by hand (2026-11-08, M1)

Components in `frontend/src/components/ui/` follow shadcn/ui (Radix primitives, `class-variance-authority`, `tailwind-merge`) but are written by hand, so no interactive CLI is needed.

## D4. Frontend reaches the backend through the Vite proxy (2026-11-08, M1)

The browser calls `/api/*` and Vite forwards to `http://127.0.0.1:8000`. Requests stay same-origin, so CORS is only a second line of defence: the backend allows only `http://localhost:5173` and `http://127.0.0.1:5173`. Both servers bind to `127.0.0.1`.

## D5. Settings: `.env` at the repo root, validated at startup (2026-11-08, M1)

`backend/app/config.py` reads the repo-root `.env` with pydantic-settings. Secrets are `SecretStr`, so they don't show up in reprs or logs. Startup (`uv run python -m app`) exits with one line per missing setting for the chosen provider, and never prints values. Defaults use fake providers, so the app runs with no accounts. The Anthropic key is optional at startup; runs that need it will check it.

## D6. SQLite through the standard library, one connection per operation (2026-11-08, M1)

`backend/app/db.py` uses `sqlite3` directly (no ORM). Each operation opens a short-lived connection with WAL mode and foreign keys on. This is safe from both request handlers and background graph threads, and fast enough for one user. Files: `data/app.db`, uploads under `data/runs/<run_id>/`. `data/` is gitignored.

## D7. Provider interfaces in `providers/base.py`; idempotency outside the Jira provider (2026-11-08, M1)

- All Protocols and their data types (`CodeProvider`, `JiraProvider`, `TranscriptProvider`, `Repo`, `FileEntry`, `NewIssue`, `CreateOutcome`, ...) live in one module, `providers/base.py`. The spec's file layout lists only implementations.
- The spec puts idempotency inside `create_issues(project_key, drafts, run_id)`. Instead, `JiraProvider` exposes primitives (`find_by_label`, `create_issues`) and the label check runs in one shared service (built in M2/M4). The fake and the real Jira then use the same idempotency code, so testing it against the fake also tests the real path.
- `CodeProvider` adds `list_repos` and `list_branches` for the pickers. Per the research, there is no `search` method: search is local over fetched files.
- Path, size and binary filters are shared in `providers/filters.py` so every code provider skips the same files.

## D8. Fake providers (2026-11-08, M1)

- `FakeCodeProvider` serves `fixtures/repo/` as repository `fixtures/demo-app`, branch `main`. It refuses paths outside that folder.
- `FakeJiraProvider` has one project (`DEMO`) and stores created issues in `data/fake_jira.json`, so label-based idempotency can be tested across a backend restart (needed for the M2 restart check). It also records every call for tests.
- Selecting a real provider before its milestone returns HTTP 501 with a message naming the milestone.

## D9. Fixtures (2026-11-08, M1)

`fixtures/` has a made-up demo app (Login and Dashboard), a VTT transcript of a design review of it, and two wireframe mockups. `fixtures/README.md` lists the six requests in the meeting and their state in the repo (missing, partial, implemented), plus one item explicitly parked (dark mode). This is the ground truth for M2 checks and the later evals.

## VERIFY items

| Item (spec section) | Status |
|---|---|
| SQLite checkpointer package and class (5) | Open, M2 |
| GitLab token scope for the tree endpoint (6.2) | Open, M3 |
| How the new createmeta endpoints mark required fields (6.3) | Open, M4 |
| API-token Basic auth on Agile (sprint) endpoints (6.3) | Open, M4 |
| LangGraph `interrupt` / `Command(resume=...)` API (7.2) | Checked in research (`from langgraph.types import interrupt, Command`); confirm against installed version in M2 |
| Anthropic structured outputs usage (7.3) | Checked in research (`client.messages.parse()` / `output_config.format`); confirm against installed SDK in M2 |
