"""A small stateful fake Jira Cloud site (respx): projects, create meta, bulk create, search,
boards and sprints. Issues created through it can be found again by label."""

import json
from typing import Any

import httpx
import respx

SITE = "https://example.atlassian.net"
TYPES = [
    {"id": "10001", "name": "Story", "subtask": False},
    {"id": "10002", "name": "Task", "subtask": False},
    {"id": "10003", "name": "Bug", "subtask": False},
    {"id": "10004", "name": "Subtask", "subtask": True},
]
BASE_FIELDS = [
    {"fieldId": "summary", "key": "summary", "name": "Summary", "required": True},
    {"fieldId": "issuetype", "key": "issuetype", "name": "Issue Type", "required": True},
    {"fieldId": "project", "key": "project", "name": "Project", "required": True},
    {"fieldId": "description", "key": "description", "name": "Description", "required": False},
    {"fieldId": "labels", "key": "labels", "name": "Labels", "required": False},
    {
        "fieldId": "reporter",
        "key": "reporter",
        "name": "Reporter",
        "required": True,
        "hasDefaultValue": True,
    },
]


class MockJira:
    def __init__(self, project: str = "A3") -> None:
        self.project = project
        self.issues: list[dict[str, Any]] = []
        self.sprint_issues: dict[int, list[str]] = {}
        self.extra_required: dict[str, list[dict[str, Any]]] = {}  # type id -> fields
        self.fail_summaries: set[str] = set()  # bulk create rejects these
        self.bulk_status: int | None = None  # force a status for bulk create
        self.router = respx.mock(base_url=SITE, assert_all_called=False)
        r = self.router
        r.get("/rest/api/3/project/search").mock(side_effect=self._projects)
        r.get(url__regex=r"/rest/api/3/issue/createmeta/(?P<key>[^/]+)/issuetypes(\?|$)").mock(
            side_effect=self._types
        )
        r.get(
            url__regex=r"/rest/api/3/issue/createmeta/(?P<key>[^/]+)/issuetypes/(?P<tid>[^/?]+)"
        ).mock(side_effect=self._fields)
        r.post("/rest/api/3/issue/bulk").mock(side_effect=self._bulk)
        r.get("/rest/api/3/search/jql").mock(side_effect=self._search)
        r.get("/rest/agile/1.0/board").mock(side_effect=self._boards)
        r.get(url__regex=r"/rest/agile/1.0/board/(?P<bid>\d+)/sprint").mock(
            side_effect=self._sprints
        )
        r.post(url__regex=r"/rest/agile/1.0/sprint/(?P<sid>\d+)/issue").mock(
            side_effect=self._add_to_sprint
        )

    # ---- handlers ----

    def _projects(self, request: httpx.Request) -> httpx.Response:
        start = int(request.url.params.get("startAt", "0"))
        projects = [{"key": self.project, "name": "App 3"}, {"key": "OPS", "name": "Ops"}]
        page = projects[start : start + 1]  # one per page, to exercise paging
        return httpx.Response(
            200, json={"values": page, "isLast": start + 1 >= len(projects), "total": 2}
        )

    def _types(self, request: httpx.Request, key: str) -> httpx.Response:
        if key != self.project:
            return httpx.Response(404, json={"errorMessages": ["No project"]})
        return httpx.Response(200, json={"issueTypes": TYPES, "total": len(TYPES), "startAt": 0})

    def _fields(self, request: httpx.Request, key: str, tid: str) -> httpx.Response:
        fields = BASE_FIELDS + self.extra_required.get(tid, [])
        return httpx.Response(200, json={"fields": fields, "total": len(fields), "startAt": 0})

    def _bulk(self, request: httpx.Request) -> httpx.Response:
        if self.bulk_status is not None:
            return httpx.Response(self.bulk_status, json={"errorMessages": ["boom"]})
        body = json.loads(request.content)
        created, errors = [], []
        for i, update in enumerate(body["issueUpdates"]):
            fields = update["fields"]
            if fields["summary"] in self.fail_summaries:
                errors.append(
                    {
                        "failedElementNumber": i,
                        "status": 400,
                        "elementErrors": {"errors": {"summary": "Summary is not allowed"}},
                    }
                )
                continue
            key = f"{self.project}-{len(self.issues) + 1}"
            self.issues.append({"key": key, **fields})
            created.append({"id": str(len(self.issues)), "key": key, "self": f"{SITE}/x"})
        return httpx.Response(201 if created else 400, json={"issues": created, "errors": errors})

    def _search(self, request: httpx.Request) -> httpx.Response:
        jql = request.url.params["jql"]
        label = jql.split('labels = "')[1].rstrip('"')
        hits = [i for i in self.issues if label in i["labels"]]
        token = request.url.params.get("nextPageToken")
        page, rest = (hits[1:], []) if token else (hits[:1], hits[1:])
        body: dict[str, Any] = {
            "issues": [{"key": i["key"], "fields": {"labels": i["labels"]}} for i in page],
            "isLast": not rest,
        }
        if rest:
            body["nextPageToken"] = "p2"
        return httpx.Response(200, json=body)

    def _boards(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "values": [
                    {"id": 2, "name": "A3 board", "type": "simple"},  # team-managed
                    {"id": 3, "name": "A3 kanban", "type": "kanban"},
                    {"id": 4, "name": "No sprints", "type": "simple"},
                ]
            },
        )

    def _sprints(self, request: httpx.Request, bid: str) -> httpx.Response:
        assert bid != "3", "kanban boards must not be asked for sprints"
        if bid == "4":
            return httpx.Response(
                400, json={"errorMessages": ["The board does not support sprints"]}
            )
        return httpx.Response(
            200,
            json={
                "values": [
                    {"id": 7, "name": "A3 Sprint 2", "state": "future"},
                    {"id": 6, "name": "A3 Sprint 1", "state": "active"},
                ],
                "isLast": True,
            },
        )

    def _add_to_sprint(self, request: httpx.Request, sid: str) -> httpx.Response:
        if sid == "99":
            return httpx.Response(404, json={"errorMessages": ["Sprint does not exist"]})
        keys = json.loads(request.content)["issues"]
        assert len(keys) <= 50
        self.sprint_issues.setdefault(int(sid), []).extend(keys)
        return httpx.Response(204)

    # ---- helpers ----

    def calls(self, method: str, fragment: str) -> list[httpx.Request]:
        return [
            c.request
            for c in self.router.calls
            if c.request.method == method and fragment in c.request.url.path
        ]
