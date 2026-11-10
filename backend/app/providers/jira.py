"""Jira Cloud provider: REST API v3 and Agile 1.0 with HTTP Basic auth (email + API token).

Endpoints used:
- GET  /rest/api/3/project/search                                   project picker
- GET  /rest/api/3/issue/createmeta/{project}/issuetypes[/{id}]     issue types, create fields
- GET  /rest/api/3/search/jql                                       label search (idempotency)
- POST /rest/api/3/issue/bulk                                       create, at most 50 per call
- GET  /rest/agile/1.0/board?projectKeyOrId=, /board/{id}/sprint    sprint picker
- POST /rest/agile/1.0/sprint/{id}/issue                            add to sprint, at most 50

The deprecated `GET /rest/api/3/search` and `GET /rest/api/3/issue/createmeta` are not used.
Creates are not retried on 5xx or timeouts (the issue may exist already); label-based
idempotency in services/tickets.py makes a later retry safe instead.
"""

import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.providers.adf import to_adf
from app.providers.base import (
    CreateField,
    CreateOutcome,
    IssueRef,
    JiraIssueType,
    JiraProject,
    NewIssue,
    ProviderError,
    Sprint,
)
from app.providers.http import Transient, with_retries

log = logging.getLogger("app.jira")

PAGE = 50
MAX_PAGES = 20
BULK_LIMIT = 50


class JiraCloudProvider:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_wait: float = 1.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(email, api_token)
        self._transport = transport
        self._retry_wait = retry_wait

    # ---------- reads ----------

    async def list_projects(self) -> list[JiraProject]:
        values = await self._offset_pages("/rest/api/3/project/search", "values", "projects")
        return [JiraProject(key=p["key"], name=p["name"]) for p in values]

    async def list_issue_types(self, project_key: str) -> list[JiraIssueType]:
        values = await self._offset_pages(
            f"/rest/api/3/issue/createmeta/{_seg(project_key)}/issuetypes",
            ("issueTypes", "values", "createMetaIssueType"),
            f"issue types of {project_key}",
        )
        return [
            JiraIssueType(id=str(t["id"]), name=t["name"], subtask=bool(t.get("subtask")))
            for t in values
        ]

    async def get_create_fields(self, project_key: str, issue_type_id: str) -> list[CreateField]:
        values = await self._offset_pages(
            f"/rest/api/3/issue/createmeta/{_seg(project_key)}/issuetypes/{_seg(issue_type_id)}",
            ("fields", "results", "values"),
            f"create fields of {project_key}",
        )
        return [
            CreateField(
                id=f.get("fieldId") or f.get("key", ""),
                name=f.get("name", f.get("fieldId", "?")),
                required=bool(f.get("required")),
                has_default=bool(f.get("hasDefaultValue")),
            )
            for f in values
        ]

    async def find_by_label(self, project_key: str, label: str) -> list[IssueRef]:
        jql = f'project = "{_jql(project_key)}" AND labels = "{_jql(label)}"'
        out: list[IssueRef] = []
        token: str | None = None
        async with self._client() as client:
            for _ in range(MAX_PAGES):
                params = {"jql": jql, "fields": "labels", "maxResults": "100"}
                if token:
                    params["nextPageToken"] = token
                data = await self._get(client, "/rest/api/3/search/jql", params, "issue search")
                for issue in data.get("issues", []):
                    labels = (issue.get("fields") or {}).get("labels") or []
                    out.append(self._ref(issue["key"], labels))
                token = data.get("nextPageToken")
                if data.get("isLast", True) or not token:
                    break
        return out

    async def list_sprints(self, project_key: str) -> list[Sprint]:
        async with self._client() as client:
            boards = await self._get(
                client,
                "/rest/agile/1.0/board",
                {"projectKeyOrId": project_key, "maxResults": str(PAGE)},
                f"boards of {project_key}",
            )
            sprints: dict[int, Sprint] = {}
            for board in boards.get("values", []):
                # Company-managed scrum boards are "scrum", team-managed ones "simple" (and
                # may have sprints enabled). Kanban boards never have sprints.
                if board.get("type") == "kanban":
                    continue
                try:
                    data = await self._get(
                        client,
                        f"/rest/agile/1.0/board/{int(board['id'])}/sprint",
                        {"state": "active,future", "maxResults": str(PAGE)},
                        f"sprints of board {board.get('name', board['id'])}",
                    )
                except ProviderError as e:
                    log.info("board %s has no sprints: %s", board.get("id"), e)
                    continue  # e.g. a team-managed board with sprints turned off
                for s in data.get("values", []):
                    sprints.setdefault(
                        int(s["id"]),
                        Sprint(
                            id=int(s["id"]),
                            name=s["name"],
                            state=s.get("state", ""),
                            board=board.get("name"),
                        ),
                    )
        return sorted(sprints.values(), key=lambda s: (s.state != "active", s.id))

    # ---------- writes ----------

    async def create_issues(self, project_key: str, issues: list[NewIssue]) -> list[CreateOutcome]:
        if len(issues) > BULK_LIMIT:
            raise ValueError(f"at most {BULK_LIMIT} issues per call")
        type_ids = {t.name: t.id for t in await self.list_issue_types(project_key)}
        outcomes: dict[int, CreateOutcome] = {}
        sendable: list[tuple[int, dict[str, Any]]] = []
        for index, issue in enumerate(issues):
            type_id = type_ids.get(issue.issue_type)
            if type_id is None:
                outcomes[index] = CreateOutcome(
                    index=index,
                    error=f"Issue type {issue.issue_type!r} does not exist in {project_key}",
                )
                continue
            sendable.append(
                (
                    index,
                    {
                        "fields": {
                            "project": {"key": project_key},
                            "issuetype": {"id": type_id},
                            "summary": issue.summary,
                            "description": to_adf(issue.description),
                            "labels": issue.labels,
                        }
                    },
                )
            )

        if sendable:
            body = {"issueUpdates": [payload for _, payload in sendable]}
            async with self._client() as client:
                response = await self._post(client, "/rest/api/3/issue/bulk", body, "bulk create")
            if response.status_code not in (201, 400):
                self._raise_for(response, "bulk create")
            data = response.json()
            failed = {
                int(e.get("failedElementNumber", -1)): _element_error(e)
                for e in data.get("errors", [])
            }
            created = iter(data.get("issues", []))
            for position, (index, _) in enumerate(sendable):
                if position in failed:
                    outcomes[index] = CreateOutcome(index=index, error=failed[position])
                    continue
                item = next(created, None)
                if item is None:
                    outcomes[index] = CreateOutcome(index=index, error="No result from Jira")
                else:
                    outcomes[index] = CreateOutcome(
                        index=index, issue=self._ref(item["key"], issues[index].labels)
                    )
        return [outcomes[i] for i in range(len(issues))]

    async def add_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> None:
        if len(issue_keys) > BULK_LIMIT:
            raise ValueError(f"at most {BULK_LIMIT} issues per call")
        async with self._client() as client:
            response = await self._post(
                client,
                f"/rest/agile/1.0/sprint/{int(sprint_id)}/issue",
                {"issues": issue_keys},
                f"sprint {sprint_id}",
            )
        if response.status_code != 204:
            self._raise_for(response, f"sprint {sprint_id}")

    # ---------- internals ----------

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            auth=self._auth,
            headers={"Accept": "application/json", "User-Agent": "meeting-to-jira-local"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=self._transport,
        )

    def _ref(self, key: str, labels: list[str]) -> IssueRef:
        return IssueRef(key=key, url=f"{self._base_url}/browse/{key}", labels=labels)

    async def _offset_pages(
        self, path: str, keys: str | tuple[str, ...], what: str
    ) -> list[dict[str, Any]]:
        names = (keys,) if isinstance(keys, str) else keys
        out: list[dict[str, Any]] = []
        async with self._client() as client:
            start = 0
            for _ in range(MAX_PAGES):
                data = await self._get(
                    client, path, {"startAt": str(start), "maxResults": str(PAGE)}, what
                )
                page: list[dict[str, Any]] = next(
                    (data[k] for k in names if isinstance(data.get(k), list)), []
                )
                out.extend(page)
                start += len(page)
                total = data.get("total")
                if not page or data.get("isLast") or (isinstance(total, int) and start >= total):
                    break
        return out

    async def _get(
        self, client: httpx.AsyncClient, path: str, params: dict[str, str], what: str
    ) -> Any:
        async def once() -> Any:
            response = await client.get(path, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                raise Transient(response)
            if response.status_code >= 400:
                self._raise_for(response, what)
            return response.json()

        return await with_retries(once, service="Jira", what=what, wait=self._retry_wait)

    async def _post(
        self, client: httpx.AsyncClient, path: str, body: dict[str, Any], what: str
    ) -> httpx.Response:
        async def once() -> httpx.Response:
            response = await client.post(path, json=body)
            if response.status_code == 429:  # rejected before processing: safe to retry
                raise Transient(response)
            if response.status_code in (401, 403, 404) or response.status_code >= 500:
                self._raise_for(response, what)
            return response

        return await with_retries(once, service="Jira", what=what, wait=self._retry_wait)

    def _raise_for(self, response: httpx.Response, what: str) -> None:
        status = response.status_code
        if status == 401:
            raise ProviderError(
                "Jira rejected JIRA_EMAIL / JIRA_API_TOKEN (wrong email, or the token expired)"
            )
        if status == 403:
            raise ProviderError(f"Jira refused access to {what}: your user lacks permission")
        if status == 404:
            raise ProviderError(f"Jira could not find {what}, or your user cannot see it")
        if status >= 500:
            raise ProviderError(
                f"Jira returned HTTP {status} for {what}. Some issues may have been created; "
                "approving again is safe and skips them."
            )
        raise ProviderError(f"Jira rejected {what}: {_error_text(response)}")


def _seg(value: str) -> str:
    """A safe URL path segment (project keys and ids are simple, but never trust input)."""
    return quote(value, safe="")


def _jql(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _element_error(error: dict[str, Any]) -> str:
    collection = error.get("elementErrors") or {}
    return _collection_text(collection) or f"HTTP {error.get('status', '?')}"


def _error_text(response: httpx.Response) -> str:
    try:
        return _collection_text(response.json()) or f"HTTP {response.status_code}"
    except ValueError:
        return f"HTTP {response.status_code}"


def _collection_text(collection: dict[str, Any]) -> str:
    parts = [str(m) for m in collection.get("errorMessages") or []]
    parts += [f"{field}: {msg}" for field, msg in (collection.get("errors") or {}).items()]
    return "; ".join(parts)[:500]
