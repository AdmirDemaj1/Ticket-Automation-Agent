# Meeting to Jira (local, single user)

Turn a meeting transcript and Figma screenshots into Jira sprint tickets. The app compares what was asked for with your code, drafts tickets with evidence, and creates them in Jira only after you review and approve.

Runs on your own machine. Spec: [Claude-Reference.md](Claude-Reference.md). Decisions: [docs/DECISIONS.md](docs/DECISIONS.md).

## Status

| Milestone | State |
|---|---|
| M1 Skeleton and fakes | Done |
| M2 Pipeline end to end on fixtures | Done |
| M3 Real code provider (GitHub; GitLab later) | Done, pending a run on a real repo |
| M4 Real Jira | Next |
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

Open http://127.0.0.1:5173 and check **Status**. With the defaults:

- the code provider serves the fixture repo in `fixtures/repo/`,
- Jira is a fake that stores issues in `data/fake_jira.json`,
- the LLM is a fake that replays the hand-written responses in `fixtures/llm/`. They fit the fixture meeting, so every run gets the same drafts whatever you upload.

### Try a run

1. **New run**: upload `fixtures/transcript.vtt`, add `fixtures/screenshots/01-login.png` and `02-dashboard.png`, keep repository `demo-app (fixture)` and Jira project `DEMO`, tick the consent box, **Start**.
2. The run page shows live progress, then the review tabs: *Summary by screen*, *Code analysis* (status, evidence, confidence) and *Draft tickets*.
3. Edit drafts, **Save edits**, choose which to include, then **Approve & create in Jira**. Every issue gets the labels `mtj-<run id>` and `mtj-<run id>-<draft id>`, so approving twice never makes duplicates.

A run paused for review survives a backend restart. A run that failed, or was interrupted by a restart mid-step, can be **retried** from its last completed step.

## Connect real providers

Edit `.env`. The backend refuses to start and lists what is missing if a provider is selected without its credentials.

- **Claude:** `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`. The model comes from `ANTHROPIC_MODEL` (default `claude-opus-5-5`), depth from `ANTHROPIC_EFFORT` (default `medium`). Each run stops at `MAX_LLM_TOKENS_PER_RUN`; the New Run page shows an estimate first.
- **GitHub:** `CODE_PROVIDER=github` and `GITHUB_TOKEN`. Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new) with *Repository access: Only select repositories* and *Repository permissions > Contents: Read-only*. Nothing else is needed. The repository picker lists exactly the repositories the token can see. The app only sends GET requests, never uses GitHub's code search, and reads at most `MAX_CODE_FILES` files and `MAX_TOTAL_CODE_BYTES` bytes per run.
- **GitLab:** not implemented yet (`CODE_PROVIDER=gitlab` returns a clear error). Planned: `GITLAB_BASE_URL` and `GITLAB_TOKEN` with scope `read_api`.
- **Jira Cloud:** `JIRA_PROVIDER=jira`, `JIRA_BASE_URL`, `JIRA_EMAIL` and `JIRA_API_TOKEN` from https://id.atlassian.com/manage-profile/security/api-tokens. The token can do anything your Jira user can, so prefer a dedicated user. (M4.)

## Develop

```bash
./scripts/check.sh    # all linters, type checks and tests (same as CI)
```

Or per side: `cd backend && uv run pytest`, `cd frontend && pnpm test`.

Layout: `backend/` (FastAPI, LangGraph, SQLite; prompts in `backend/app/prompts/`), `frontend/` (React + Vite), `fixtures/` (demo repo, transcript, screenshots), `docs/`. All run data lives under `data/` (gitignored).

## Privacy and risks

- Meeting transcripts and source code are sensitive. Make sure you are allowed to send them to the Claude API, and tell meeting participants if a recording or bot was used.
- Code analysis by an LLM can miss things. Treat findings as a starting point with evidence, not as an audit.
- Nothing is written to Jira without your explicit approval.
