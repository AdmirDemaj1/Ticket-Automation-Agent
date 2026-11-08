# Third-party integrations: feasibility research

> Written for the multi-user roadmap ([AGENT_SPEC_meeting-to-jira.md](../AGENT_SPEC_meeting-to-jira.md)). v1 ([Claude-Reference.md](../Claude-Reference.md)) avoids most of these issues by using personal tokens: a GitHub fine-grained token with `Contents: read`, a GitLab token with `read_api`, and a Jira API token. The GitHub/GitLab search findings, the Jira findings (createmeta, bulk limit, labels) and the Claude/LangGraph findings still apply to v1.

Researched on 2026-11-08 from vendor docs, with a few community threads where the docs were silent. Each finding is marked:

- **Confirmed**: read on the official documentation page.
- **Reported**: from a community thread or a vendor blog, not the reference docs.
- **Open**: could not confirm. Must be checked against a real account before or during that milestone.

APIs change. Re-check each item when its milestone starts.

## Summary

| Integration | Feasible? | Main blocker or risk | Spec changes needed |
|---|---|---|---|
| Jira Cloud (OAuth 2.0 3LO) | **Yes** | Each customer site may require custom fields. App must be "shared" for other orgs to install it. | Use granular scopes for sprints. Use the new createmeta endpoints. Idempotency via labels, not entity properties. |
| GitHub | **Yes, but only via a GitHub App** | OAuth apps cannot get read-only access to private code. Code search only covers the default branch. | Use a GitHub App with `Contents: read`. Do not use the search API; search locally instead. |
| GitLab | **Yes** | Blob search is Premium/Ultimate only. | Use `read_api` (+ `read_repository`). Do not rely on the search API; search locally instead. |
| Microsoft Teams (Graph) | **Yes, with tenant admin involvement** | Admin consent is required for the transcript permission, and an admin can disable transcript API access tenant-wide. Listing transcripts in bulk is application-permission only. | Delegated flow only: pick from the calendar, then resolve the meeting, then fetch its transcripts. |
| Spinach | **Yes, via MCP only (no public API for our use)** | The REST API is Enterprise-only. Plan limits are unclear. | Implement `SpinachProvider` as an MCP client with OAuth (dynamic client registration and PKCE are supported). |
| Anthropic Claude | **Yes** | `langchain-anthropic` structured output may use forced tool choice, which current models reject. | Use the `anthropic` SDK's structured outputs directly in nodes. Set `ANTHROPIC_MODEL=claude-opus-5-5` by default. |
| LangGraph | **Yes** | Nodes re-run from the start on resume. | Keep side effects out of `human_review` before `interrupt()`. |

---

## 1. Jira Cloud (Atlassian OAuth 2.0 3LO)

**Auth flow (Confirmed)**
- Authorize at `https://auth.atlassian.com/authorize` with `audience=api.atlassian.com`, `client_id`, `scope`, `redirect_uri`, `state`, `response_type=code`, `prompt=consent`.
- Exchange the code at `POST https://auth.atlassian.com/oauth/token`.
- The docs page does not mention PKCE support. We rely on `state` plus the client secret held server-side.
- Refresh tokens **rotate**. Every refresh returns a new refresh token and disables the old one, so we must save it each time. Tokens expire after **90 days of inactivity**. A **10-minute reuse window** tolerates concurrent refreshes. `offline_access` is required to get a refresh token. A `403 invalid_grant` means the user must reconnect (our `needs_reauth` state).
- Discover sites with `GET https://api.atlassian.com/oauth/token/accessible-resources`. A user can have several sites, so the UI needs a site picker. Call the API at `https://api.atlassian.com/ex/jira/{cloudId}/rest/api/3/...`.

**Distribution (Confirmed)**
- 3LO apps are private by default. "Sharing" must be enabled in the developer console before other organizations can install the app.
- Users of an app Atlassian has not reviewed see a warning. Review goes through the Marketplace process and does not require a public listing.
- Atlassian requires **one distributable 3LO app**. Asking customers to create their own app or paste API tokens does not meet its security requirements.

**Scopes**
- Issues and projects: classic `read:jira-work write:jira-work offline_access` (+ `read:jira-user` if we show assignees). Confirmed in principle; check exact names in the developer console.
- Sprints (Agile API `/rest/agile/1.0/...`): Jira Software has **no classic scopes**. Use granular scopes: `read:sprint:jira-software`, `write:sprint:jira-software` (moving issues into a sprint), plus board read scopes (Confirmed). Classic and granular scopes can be mixed (Reported).
- Developers report `401 "scope does not match"` on Agile endpoints when the scopes were added after the user consented. Users must re-consent after any scope change (Reported). Atlassian confirms that changing scopes requires re-consent.

**Creating issues**
- `POST /rest/api/3/issue/bulk` accepts **up to 50 issues** per request (Confirmed by Atlassian's announcement). Batch in chunks of 50.
- `GET /rest/api/3/issue/createmeta` is **deprecated**. Replacements (Reported in Atlassian's developer forum, Open in the reference docs):
  - `GET /rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes`
  - `GET /rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes/{issueTypeId}` (paginated, one call per issue type)
- Use these to detect required custom fields and fail clearly, as the spec asks.

**Idempotency (Confirmed constraint)**
- Jira 3LO apps **cannot declare searchable entity properties**, so a property cannot be found with JQL. The spec's "internal property" idea does not work for lookup.
- Use labels instead. Put a run label (`mtj-<runId>`) and a per-ticket label (`mtj-<runId>-<tempId>`) on each issue. Before creating, search with JQL `labels = "mtj-<runId>"`. Users can see these labels, so the UI should say so.

## 2. GitHub

**Key finding (Confirmed in GitHub docs): OAuth apps cannot request read-only access to private code.** Private repository access requires the `repo` scope, which is full read/write. This conflicts with the spec's "code access read-only" security rule.

**Use a GitHub App instead**
- Set the repository permission `Contents: read` (plus `Metadata: read`, which is always included). Read-only is enforced by GitHub.
- The user, or an org owner, installs the app on chosen repositories only. Some organizations require an owner to approve installs.
- Two token types:
  - **Installation tokens**: short-lived, created by our server from the app's private key. Simplest for reading code.
  - **User access tokens**: act on behalf of the signed-in user, limited to both the app's permissions and the user's own access. To my knowledge they expire after 8 hours and come with refresh tokens. Open: check the current docs.
- Env vars change from `GITHUB_CLIENT_ID/SECRET` to also include `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY` and `GITHUB_APP_SLUG`. The spec already mentions this option.

**Reading code (Confirmed)**
- Git trees API (recursive) and blobs/contents API, as the spec says.
- **The code search API only searches the default branch.** It is limited to **10 requests per minute** and to files under 384 KB. It cannot serve the spec's "repo + branch" choice.
- Instead, `CodeProvider.search` should search locally: filter the tree by path, then grep the files we already fetched within budget. A branch tarball (`GET /repos/{owner}/{repo}/tarball/{ref}`, `Contents: read`) is a cheaper alternative for small and medium repos.

## 3. GitLab

**Auth (Confirmed)**
- OAuth 2.0 authorization code flow, with PKCE supported. The app is registered under the user's (or group's) Applications page. Self-managed GitLab needs its own app registration and base URL, so add a `GITLAB_BASE_URL` setting.
- Scopes:
  - `read_api` gives read access to the API, including groups and projects.
  - `read_repository` gives read-only repository access over Git-over-HTTP and the Repository Files API.
  - `api` is full read/write. **Do not request it.**
- Open: which scope the repository tree endpoint needs. Request `read_api` + `read_repository` and test.

**Search (Confirmed)**
- Project search with `scope=blobs` is a **Premium/Ultimate feature** and supports a `ref` parameter.
- Do not depend on it. Use the same local search approach as GitHub.

## 4. Microsoft Teams transcripts (Microsoft Graph)

**Permissions (Confirmed)**
- Listing transcripts for a meeting: `GET /me/onlineMeetings/{id}/transcripts`.
  - Delegated (work or school): `OnlineMeetingTranscript.Read.All`. **Admin consent required.**
  - Personal Microsoft accounts: **not supported**.
- The tenant-wide endpoint `getAllTranscripts` is **application-permission only**. Application permissions also require the tenant admin to create an *application access policy*. This does not fit a self-service SaaS. Avoid it for the MVP.
- **Tenant admin switch:** an admin can turn off "Graph API access to transcripts". Every transcript call then returns `403` with inner error `GraphAccessToTranscriptsDisabled`, and there is no workaround. Show this error to the user.
- A second admin setting can turn off **speaker attribution**. The transcript then comes back without speaker names. The `Transcript.segments[].speaker` field is already optional.
- Content comes as VTT, which matches the spec.
- The Teams transcript APIs are **no longer metered** (no billing setup needed) since 2025-08-25.

**Finding the meeting (Confirmed)**
There is no delegated "list my meetings with transcripts" endpoint. Use three steps:
1. List the user's calendar events (`Calendars.Read`, delegated, no admin consent) and keep those with `isOnlineMeeting` and a Teams join URL.
2. Resolve the meeting: `GET /me/onlineMeetings?$filter=JoinWebUrl eq '{joinWebUrl}'` (`OnlineMeetings.Read`, delegated). Both the organizer's and an attendee's token are accepted for this call.
3. List and download transcripts: `GET /me/onlineMeetings/{id}/transcripts`, then `.../transcripts/{transcriptId}/content`.

**Limitations**
- Only meetings with transcription turned on have a transcript.
- Meetings created with the create-onlineMeeting API that are not on a calendar are not supported (Confirmed).
- Transcripts are only available until the meeting expires (Confirmed).
- **Open:** whether an *attendee* (not the organizer) can fetch transcripts with delegated permission. Community reports conflict. Test with a real tenant in M5.
- Channel meetings are documented as beta in places. Expect gaps.

**Scopes to request:** `offline_access`, `Calendars.Read`, `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All` (admin consent). The UI should tell users their IT admin must approve the app once per tenant.

## 5. Spinach

**API (Reported, from Spinach's own blogs)**
- Spinach's REST API and webhooks are **Enterprise-only, with custom pricing**. They are not a general integration path.

**MCP server (Confirmed by probing the server's public OAuth metadata on 2026-11-08, and by Spinach's help center)**
- Endpoint `https://mcp.spinach.ai/mcp`, transport streamable HTTP.
- Without a token it returns `401` with a pointer to its OAuth metadata.
- OAuth authorization server is `https://mcp.spinach.ai`:
  - **Dynamic client registration** at `/oauth/register`, open (no auth needed to register).
  - **PKCE S256** supported. Grant type: authorization code.
  - Scopes: `mcp:read`, `mcp:write`. We only need `mcp:read`.
  - Token endpoint auth: `client_secret_post`.
  - Note: `refresh_token` is **not** listed in the supported grant types. If tokens expire, the user may have to reconnect (Open).
- Capabilities (help center): search meetings, list meetings with filters (date range, participants, title), and fetch a full meeting by ID, **including the transcript**, summary, action items and decisions.
- Limits (help center): tools are rate-limited per hour (no figure given). Authorized connections last 12 months. Video only covers the last 7 days; transcripts are not limited that way.
- Plans: marketing pages say MCP access requires Business or Enterprise plans. The help center does not say. **Open**: confirm on a real account.
- Tool names and their input/output schemas: **Open**. List them with `tools/list` after connecting a test account. Our adapter must map the transcript format to `Transcript`.

**Conclusion:** build `SpinachProvider` as an MCP client using the official `mcp` Python SDK over streamable HTTP. NestJS runs the OAuth flow (register the client once, then the PKCE authorization code flow) and stores the token in the vault, like the other providers. If a user's plan does not include MCP, the provider shows "not available on your Spinach plan".

## 6. Anthropic Claude (LLM)

Current models (`claude-api` skill reference, cached 2026-10-06):
- `claude-opus-5-5`: default, 1M context, vision input supported.
- `claude-sonnet-5-5`, `claude-haiku-5-5`: cheaper options for bulk steps.
- `claude-fable-5-1`: most capable, priced above Opus.

Set `ANTHROPIC_MODEL=claude-opus-5-5`. A cheaper model for some nodes is a later cost decision, made only after measuring.

API facts that affect the agent design:
- **Structured outputs:** use `output_config.format` or the SDK's `client.messages.parse()` with a Pydantic schema. This covers the spec's "structured output validated by Pydantic". The model output is constrained to the schema; we still validate with Pydantic and keep the retry-once rule.
- **Forced tool use returns 400** on Opus 5.5 and Sonnet 5.5 (`tool_choice` of `any` or a named tool). `langchain-anthropic`'s `with_structured_output` has historically relied on a forced tool call. Recommendation: **call the `anthropic` SDK directly inside nodes** (the spec allows this) rather than `langchain-anthropic`.
- **Thinking:** cannot be turned off on Opus 5.5. Control depth with `output_config.effort` (default `medium`). No `temperature` or `budget_tokens`.
- Check `stop_reason == "refusal"` before reading content. Refusal fallbacks are available.
- **Vision:** send screenshots as base64 `image` content blocks.
- **Budgets:** use `usage.input_tokens` and `usage.output_tokens` from each response to enforce `MAX_LLM_TOKENS_PER_RUN`. `messages.count_tokens` can estimate cost before a call.

## 7. LangGraph human-in-the-loop (Confirmed, current docs)

- `from langgraph.types import interrupt, Command`. Call `interrupt(payload)` in the node and resume with `graph.invoke(Command(resume=decision), config)` using the same `thread_id`. `langgraph>=1.2.12` adds `response_schema=` to validate the resume value.
- A checkpointer is required. The docs examples use in-memory and SQLite savers. For Postgres we use the `langgraph-checkpoint-postgres` package (its exact class name and setup: check during M2).
- **On resume, the node re-runs from its start.** Anything before `interrupt()` must be idempotent. Never wrap `interrupt()` in a bare `try/except`, because it would swallow the pause signal. This matters for the spec's "wrap each node in try/except" rule.
- With `invoke()`, the interrupt payload appears under `result["__interrupt__"]`.

---

## Changes to make in `docs/DECISIONS.md` when each milestone starts

1. **M2:** Use the `anthropic` SDK with `messages.parse()` instead of `langchain-anthropic`. Keep `interrupt()` outside the nodes' try/except.
2. **M3:** Replace GitHub OAuth App with a GitHub App (`Contents: read`). Use local search instead of the GitHub and GitLab search APIs. Add `GITLAB_BASE_URL`.
3. **M4:** Use granular Jira Software scopes for sprints, the new createmeta endpoints, and label-based idempotency. Batch bulk creates in chunks of 50. Add a site picker for multiple Jira sites.
4. **M5:** Microsoft Graph delegated flow (calendar → meeting → transcripts) with an admin-consent notice. Spinach provider via MCP with dynamic client registration.

## Open questions to test with real accounts

| # | Question | Needed by |
|---|---|---|
| 1 | Exact current names of the Jira scopes for boards and sprints, and whether Agile endpoints work with them on a fresh consent. | M4 |
| 2 | Whether the new createmeta endpoints return everything needed to detect required custom fields. | M4 |
| 3 | Which GitLab scope the repository tree endpoint needs. | M3 |
| 4 | Whether an attendee (non-organizer) can read transcripts with delegated permission. | M5 |
| 5 | Which Spinach plans include MCP, the MCP tool names and schemas, token lifetime, and whether refresh tokens exist. | M5 |
| 6 | GitHub App user access token lifetime and refresh behaviour (if we use user tokens rather than installation tokens). | M3 |

## Sources

- Microsoft: [Fetch meeting transcripts and recordings (overview)](https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/meeting-transcripts/overview-transcripts), [List transcripts](https://learn.microsoft.com/en-us/graph/api/onlinemeeting-list-transcripts), [getAllTranscripts](https://learn.microsoft.com/en-us/graph/api/onlinemeeting-getalltranscripts), [Get onlineMeeting](https://learn.microsoft.com/en-us/graph/api/onlinemeeting-get), [Get callTranscript](https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0), [Delegated attempts thread](https://techcommunity.microsoft.com/t5/teams-developer/need-help-in-understanding-delegated-permissions-for/m-p/4262463), [Co-organizer failure thread](https://learn.microsoft.com/en-us/answers/questions/2278999/microsoft-graph-api-failed-to-execute-backend-requ)
- Atlassian: [OAuth 2.0 (3LO) apps](https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/), [Jira Software scopes](https://developer.atlassian.com/cloud/jira/software/scopes-for-oauth-2-3LO-and-forge-apps/), [Jira platform scopes](https://developer.atlassian.com/cloud/jira/platform/scopes-for-oauth-2-3LO-and-forge-apps/), [Bulk create limit change](https://community.developer.atlassian.com/t/change-on-number-of-issues-can-be-created-in-a-single-bulk-create-issues-request/54083), [Createmeta deprecation](https://community.developer.atlassian.com/t/create-issue-meta-endpoint-deprecation/75413), [Agile 401 scope mismatch thread](https://community.developer.atlassian.com/t/oauth-2-0-3lo-granular-jira-software-scopes-present-in-token-but-rest-agile-1-0-returns-401-scope-does-not-match/100456)
- GitHub: [Scopes for OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps), [Authorizing OAuth apps](https://help.github.com/articles/authorizing-oauth-apps/), [Search code](https://docs.github.com/en/rest/search/search#search-code)
- GitLab: [OAuth 2.0 identity provider API](https://docs.gitlab.com/api/oauth2), [Search API](https://docs.gitlab.com/api/search/)
- Spinach: [MCP configuration](https://help.spinach.ai/en/articles/11030670-mcp-configuration), [Claude MCP integration](https://help.spinach.ai/en/articles/15304675-claude-mcp-integration), [MCP server setup blog](https://www.spinach.ai/blog/meeting-transcript-mcp-server-setup), and the server's public metadata at `https://mcp.spinach.ai/.well-known/oauth-authorization-server` (fetched 2026-11-08)
- LangGraph: [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- Anthropic: `claude-api` skill reference (model table cached 2026-10-06)
