# Security

Checklist from spec section 11. Each item is ticked only with evidence (a test, a file, or a config line).

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Tokens encrypted at rest, never logged, never in graph state | Not started | M1 (vault), M2 (graph state) |
| 2 | Least-privilege scopes (code read-only, Jira create-only) | Not started | M3/M4 |
| 3 | Human approval mandatory before Jira writes | Not started | M2 |
| 4 | Prompt-injection defense | Not started | M2/M6 |
| 5 | Internal service auth; agent not reachable from the internet | Done (M0) | `apps/agent/app/security.py` (constant-time `X-Service-Token`), `apps/agent/tests/test_security.py`; Compose binds agent to `127.0.0.1` only; no OpenAPI/docs exposed on the agent. |
| 6 | Per-user data isolation; deletion; retention | Not started | M1 (isolation), M6 (retention) |
| 7 | OWASP basics | Partial | Helmet headers, CORS allowlist (`WEB_ORIGIN`), global `ValidationPipe` with whitelist, rate limiting (`ThrottlerGuard`). OAuth state/PKCE in M3. Dependency scanning in M6. |
| 8 | AI-processing consent notice in UI | Not started | M2 |

## Logging

- pino redacts `authorization`, `cookie`, `x-service-token` request headers and `set-cookie` response headers (`apps/api/src/app.module.ts`).
- Request bodies are never logged.
- Env validation errors name the bad key, never the value (`apps/api/src/config/env.spec.ts`).
