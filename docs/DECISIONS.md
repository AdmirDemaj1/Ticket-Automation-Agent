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

## D10. LLM switch and the fake LLM (2026-11-09, M2)

`LLM_PROVIDER=anthropic|fake`, default `fake`. The fake replays `fixtures/llm/<step>.json`. These responses were **written by hand** to match the fixture meeting and the ground truth in `fixtures/README.md`; they are not recordings of real Claude output. With the fake, every run returns the same drafts whatever the transcript, which is enough to exercise the pipeline and UI. `ANTHROPIC_API_KEY` is now required at startup only when `LLM_PROVIDER=anthropic` (this updates D5).

## D11. Anthropic SDK usage (2026-11-09, M2)

- SDK `anthropic` 2.6 (it uses `httpx2`, so `respx` cannot mock it; LLM tests inject a stub client instead).
- `client.beta.messages.parse(output_format=<Pydantic model>)`, reading `parsed_output`, with a text-block fallback selected by `type`. Effort comes from `ANTHROPIC_EFFORT` (default `medium`, set explicitly). No `thinking`, `temperature` or `tool_choice` is sent.
- Server-side refusal fallback is on by default (`betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`); `ANTHROPIC_REFUSAL_FALLBACK=false` turns it off. A final `stop_reason == "refusal"` fails the step with the category. `max_tokens` truncation also fails the step.
- Validation failures are retried once with the error appended, then the step fails.
- Transient errors use the SDK's own retries (`max_retries=2`, 3 tries, exponential backoff) instead of `tenacity`. `tenacity` comes back with the HTTP code and Jira providers (M3/M4).
- Token budget: input + output + cache tokens are summed into `tokens_used` in graph state and checked before every call. Tokens spent on an attempt whose output the SDK rejects are not counted (small undercount; revisit in M6).

## D12. Graph design (2026-11-09, M2)

- `AsyncSqliteSaver` in `data/checkpoints.db` (separate from `data/app.db`), `thread_id = run_id`.
- State holds plain JSON (dicts/lists), not Pydantic objects, so checkpoints need no deserialization allowlist. Nodes validate into models when they read.
- `meeting_analysis` is a structured `MeetingAnalysis` (screens with feedback, decisions, actions, open questions; parked; notes) instead of a string, so the UI can show "Summary by screen". The spec's state lists only `code_candidates`; `code_files` (path to text) is added so `compare_with_code` can use what `read_code` fetched. Both live in the local checkpoint only.
- Providers and the LLM are passed to nodes through a `Deps` object closed over at build time, never through state or `configurable`.
- LLM output is checked by code: paths not in the repository are dropped from the read plan; evidence must point at a file that was read and at lines inside it; `implemented`/`partial` without valid evidence becomes `unclear`/`low`; every requirement gets a finding; draft types are limited to the chosen issue types; duplicate titles are merged; drafts marked `already_done` with all-high-confidence `implemented` findings start unselected.
- `human_review` does nothing before `interrupt()` and has no progress wrapper (the wrapper's events would repeat on resume). The run manager emits the "ready for review" event after the graph pauses.
- `create_tickets` raises `ApprovalRequired` unless `review.decision == "approve"`, and it uses only the drafts in the review payload. The API builds that payload from the saved drafts, not from the request body.
- Runs that were mid-step when the backend stopped are marked `failed` on startup; **Retry** resumes from the last checkpoint (`ainvoke(None)`), re-running only the failed step onward.
- Unexpected exceptions show only their type to the user (their text may contain transcript or code) and are logged with a traceback.

## D13. Uploads (2026-11-09, M2)

Images are checked by magic bytes, then decoded with Pillow (pixel-count limit), EXIF orientation applied, and re-encoded from raw pixels, which drops EXIF, GPS and ICC data. They are also downscaled to at most 1568 px on the long side: this keeps them under the Claude API image limits (the 8 MB upload limit is above the API's per-image limit) and cuts token use. Transcripts: `.vtt`, `.txt`, `.docx` or pasted text, up to `MAX_TRANSCRIPT_BYTES` (2 MB). Everything is validated in memory before the run row and files are created, so a rejected request stores nothing. `Name: text` lines count as speakers when at least 60% of lines match and at least one name repeats.

## D14. SSE (2026-11-09, M2)

`GET /runs/{id}/events` polls the `run_events` table every 0.5 s, sends `id:` on each event, honours `Last-Event-ID` (and `?after=`), sends a heartbeat comment every 15 s, and ends with `event: end` once the run is terminal. The stream stays open while a run awaits review. The browser's `EventSource` handles reconnects; the UI closes it on `end` and reopens it after a retry.

## D15. Deferred from M2 (2026-11-09)

- **Sprint assignment**: `sprint_id` is accepted but ignored until real Jira (M4). The New Run page says tickets go to the backlog.
- **Playwright happy path** (spec section 10): deferred to M6, so no browser download is needed yet. Vitest covers the New Run form and the review screen.
- **Local grep over fetched files** (spec 6.2): M2 picks files by keyword ranking plus the LLM plan. Grep-based search arrives with the real code providers (M3), where repositories are large enough to need it.
- **Delete run data and retention** (spec security 6): M6.

## VERIFY items

| Item (spec section) | Status |
|---|---|
| SQLite checkpointer package and class (5) | Resolved (M2): package `langgraph-checkpoint-sqlite` 3.1, class `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` (`from_conn_string`) |
| GitLab token scope for the tree endpoint (6.2) | Open, M3 |
| How the new createmeta endpoints mark required fields (6.3) | Open, M4 |
| API-token Basic auth on Agile (sprint) endpoints (6.3) | Open, M4 |
| LangGraph `interrupt` / `Command(resume=...)` API (7.2) | Resolved (M2): `from langgraph.types import interrupt, Command` in langgraph 1.2; resume re-runs the node from its start; tested across a checkpointer restart |
| Anthropic structured outputs usage (7.3) | Resolved (M2): see D11. Checked against the installed SDK only; no call to the real API has been made yet |
