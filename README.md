# Meeting to Jira (local, single user)

Turn a meeting transcript and Figma screenshots into Jira sprint tickets. The app compares what was asked for with your code, drafts tickets with evidence, and creates them in Jira only after you review and approve.

Runs on your own machine. Spec: [Claude-Reference.md](Claude-Reference.md). Decisions: [docs/DECISIONS.md](docs/DECISIONS.md).

## Status

| Milestone | State |
|---|---|
| M1 Skeleton and fakes | Done |
| M2 Pipeline end to end on fixtures | Next |
| M3 Real code provider (GitHub/GitLab) | Not started |
| M4 Real Jira | Not started |
| M5 Real-meeting trial | Not started |
| M6 Hardening | Not started |

## Quick start (fake providers, no accounts)

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20.19+ with pnpm 10.

```bash
cp .env.example .env              # defaults use fake providers

# terminal 1: backend on http://127.0.0.1:8000
cd backend && uv sync && uv run python -m app

# terminal 2: frontend on http://127.0.0.1:5173
cd frontend && pnpm install && pnpm dev
```

Open http://127.0.0.1:5173 and check **Status**. With the defaults, the code provider serves the fixture repo in `fixtures/repo/` and Jira is a fake that stores issues in `data/fake_jira.json`.

## Connect real providers

Edit `.env`. The backend refuses to start and lists what is missing if a provider is selected without its credentials.

- **Claude:** `ANTHROPIC_API_KEY`. The model comes from `ANTHROPIC_MODEL` (default `claude-opus-5-5`).
- **GitHub:** `CODE_PROVIDER=github` and `GITHUB_TOKEN`, a fine-grained personal access token with *Contents: Read-only* on selected repositories only. (Milestone M3.)
- **GitLab:** `CODE_PROVIDER=gitlab`, `GITLAB_BASE_URL` and `GITLAB_TOKEN` with scope `read_api`. (M3.)
- **Jira Cloud:** `JIRA_PROVIDER=jira`, `JIRA_BASE_URL`, `JIRA_EMAIL` and `JIRA_API_TOKEN` from https://id.atlassian.com/manage-profile/security/api-tokens. The token can do anything your Jira user can, so prefer a dedicated user. (M4.)

## Develop

```bash
./scripts/check.sh    # all linters, type checks and tests (same as CI)
```

Or per side: `cd backend && uv run pytest`, `cd frontend && pnpm test`.

Layout: `backend/` (FastAPI, LangGraph from M2, SQLite), `frontend/` (React + Vite), `fixtures/` (demo repo, transcript, screenshots), `docs/`. All run data lives under `data/` (gitignored).

## Privacy and risks

- Meeting transcripts and source code are sensitive. Make sure you are allowed to send them to the Claude API, and tell meeting participants if a recording or bot was used.
- Code analysis by an LLM can miss things. Treat findings as a starting point with evidence, not as an audit.
- Nothing is written to Jira without your explicit approval.
