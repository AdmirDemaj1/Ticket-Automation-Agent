# Security

Checklist from spec section 11. Each item is ticked only with evidence (a test, a file, or a config line).

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Tokens encrypted at rest, never logged, never in graph state | Partial (M1) | Vault: `apps/api/src/crypto/token-cipher.ts` (AES-256-GCM, key ids, AAD binding) with `token-cipher.spec.ts` (round-trip, tamper, wrong AAD, rotation); `test/connections.e2e-spec.ts` asserts DB rows hold no plaintext and API responses hold no token material. Graph state check in M2. |
| 2 | Least-privilege scopes (code read-only, Jira create-only) | Not started | M3/M4 |
| 3 | Human approval mandatory before Jira writes | Not started | M2 |
| 4 | Prompt-injection defense | Not started | M2/M6 |
| 5 | Internal service auth; agent not reachable from the internet | Done (M0) | `apps/agent/app/security.py` (constant-time `X-Service-Token`), `apps/agent/tests/test_security.py`; Compose binds agent to `127.0.0.1` only; no OpenAPI/docs exposed on the agent. |
| 6 | Per-user data isolation; deletion; retention | Partial (M1) | Global JWT guard, routes are private by default (`apps/api/src/auth/jwt-auth.guard.ts`). `test/connections.e2e-spec.ts`: another user cannot list, disconnect or decrypt a user's connections. Deletion and retention in M6. |
| 7 | OWASP basics | Partial | Helmet headers, CORS allowlist (`WEB_ORIGIN`), global `ValidationPipe` with whitelist + forbid unknown fields, rate limiting (global + stricter on login/register). Refresh cookie `httpOnly`/`SameSite=Strict`/`Secure` in production, Origin check on cookie endpoints, rotation with reuse detection (`test/auth.e2e-spec.ts`). argon2id passwords. OAuth state/PKCE in M3. Dependency scanning in M6. |
| 8 | AI-processing consent notice in UI | Not started | M2 |

## Logging

- pino redacts `authorization`, `cookie`, `x-service-token` request headers and `set-cookie` response headers (`apps/api/src/app.module.ts`).
- Request bodies are never logged.
- Env validation errors name the bad key, never the value (`apps/api/src/config/env.spec.ts`).

## Audit log

Recorded in `audit_log` (`apps/api/src/audit/audit.service.ts`): register, login, failed login, logout, refresh-token reuse, connection connected / disconnected / needs_reauth. Run events come in M2. Audit `meta` must never contain secrets or content.
