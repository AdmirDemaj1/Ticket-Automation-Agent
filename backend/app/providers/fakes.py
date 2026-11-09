"""Fake providers so the whole app runs with no accounts.

- FakeCodeProvider serves a local folder (the fixture repo) as one repository.
- FakeJiraProvider keeps issues in a JSON file and records every call.
"""

import json
import threading
from pathlib import Path
from typing import Any

from app.providers.base import (
    CreateField,
    CreateOutcome,
    FileEntry,
    IssueRef,
    JiraIssueType,
    JiraProject,
    NewIssue,
    ProviderError,
    Repo,
    Sprint,
)
from app.providers.filters import looks_binary, should_skip

FAKE_REPO_ID = "fixtures/demo-app"
FAKE_BRANCHES = ("main",)


class FakeCodeProvider:
    def __init__(self, root: Path, max_bytes: int) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes

    async def list_repos(self) -> list[Repo]:
        return [Repo(id=FAKE_REPO_ID, name="demo-app (fixture)", default_branch="main")]

    async def list_branches(self, repo: str) -> list[str]:
        self._check(repo, "main")
        return list(FAKE_BRANCHES)

    async def list_tree(self, repo: str, ref: str) -> list[FileEntry]:
        self._check(repo, ref)
        entries = []
        for file in sorted(self.root.rglob("*")):
            if not file.is_file():
                continue
            rel = file.relative_to(self.root).as_posix()
            size = file.stat().st_size
            if not should_skip(rel, size, self.max_bytes):
                entries.append(FileEntry(path=rel, size=size))
        return entries

    async def get_file(self, repo: str, ref: str, path: str, max_bytes: int) -> str | None:
        self._check(repo, ref)
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root) or not target.is_file():
            return None
        if target.stat().st_size > max_bytes:
            return None
        data = target.read_bytes()
        if looks_binary(data):
            return None
        return data.decode("utf-8", errors="replace")

    def _check(self, repo: str, ref: str) -> None:
        if repo != FAKE_REPO_ID:
            raise ProviderError(
                f"Unknown repository {repo!r} (fake provider serves {FAKE_REPO_ID})"
            )
        if ref not in FAKE_BRANCHES:
            raise ProviderError(f"Unknown branch {ref!r}")


class FakeJiraProvider:
    """Behaves like a tiny Jira: one project, three issue types, label search, creates."""

    PROJECTS = (JiraProject(key="DEMO", name="Demo project (fake)"),)
    ISSUE_TYPES = (
        JiraIssueType(id="10001", name="Story"),
        JiraIssueType(id="10002", name="Task"),
        JiraIssueType(id="10003", name="Bug"),
        JiraIssueType(id="10004", name="Sub-task", subtask=True),
    )
    SPRINTS = (
        Sprint(id=1, name="DEMO Sprint 1", state="active", board="DEMO board"),
        Sprint(id=2, name="DEMO Sprint 2", state="future", board="DEMO board"),
    )

    def __init__(self, store_path: Path, base_url: str = "https://fake-jira.local") -> None:
        self.store_path = store_path
        self.base_url = base_url
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._lock = threading.Lock()

    async def list_projects(self) -> list[JiraProject]:
        self._record("list_projects")
        return list(self.PROJECTS)

    async def list_issue_types(self, project_key: str) -> list[JiraIssueType]:
        self._record("list_issue_types", project_key=project_key)
        self._check_project(project_key)
        return list(self.ISSUE_TYPES)

    async def get_create_fields(self, project_key: str, issue_type_id: str) -> list[CreateField]:
        self._record("get_create_fields", project_key=project_key, issue_type_id=issue_type_id)
        self._check_project(project_key)
        return [
            CreateField(id="summary", name="Summary", required=True),
            CreateField(id="issuetype", name="Issue Type", required=True),
            CreateField(id="project", name="Project", required=True),
            CreateField(id="description", name="Description", required=False),
            CreateField(id="labels", name="Labels", required=False),
        ]

    async def find_by_label(self, project_key: str, label: str) -> list[IssueRef]:
        self._record("find_by_label", project_key=project_key, label=label)
        issues = self._load()["issues"]
        return [
            self._ref(i["key"], i["labels"])
            for i in issues
            if label in i["labels"] and i["key"].startswith(f"{project_key}-")
        ]

    async def create_issues(self, project_key: str, issues: list[NewIssue]) -> list[CreateOutcome]:
        self._record("create_issues", project_key=project_key, count=len(issues))
        self._check_project(project_key)
        outcomes = []
        with self._lock:
            store = self._load()
            for index, issue in enumerate(issues):
                store["next_id"] += 1
                key = f"{project_key}-{store['next_id']}"
                store["issues"].append({"key": key, **issue.model_dump()})
                outcomes.append(CreateOutcome(index=index, issue=self._ref(key)))
            self._save(store)
        return outcomes

    async def list_sprints(self, project_key: str) -> list[Sprint]:
        self._record("list_sprints", project_key=project_key)
        self._check_project(project_key)
        return list(self.SPRINTS)

    async def add_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> None:
        self._record("add_to_sprint", sprint_id=sprint_id, count=len(issue_keys))
        if sprint_id not in {s.id for s in self.SPRINTS}:
            raise ProviderError(f"Sprint {sprint_id} not found")
        with self._lock:
            store = self._load()
            for issue in store["issues"]:
                if issue["key"] in issue_keys:
                    issue["sprint_id"] = sprint_id
            self._save(store)

    def stored_issues(self) -> list[dict[str, Any]]:
        """Test/debug helper."""
        issues: list[dict[str, Any]] = self._load()["issues"]
        return issues

    def _ref(self, key: str, labels: list[str] | None = None) -> IssueRef:
        return IssueRef(key=key, url=f"{self.base_url}/browse/{key}", labels=labels or [])

    def _check_project(self, project_key: str) -> None:
        if project_key not in {p.key for p in self.PROJECTS}:
            raise ProviderError(f"Unknown Jira project {project_key!r}")

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))

    def _load(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return {"next_id": 0, "issues": []}
        data: dict[str, Any] = json.loads(self.store_path.read_text("utf-8"))
        return data

    def _save(self, store: dict[str, Any]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, indent=2), "utf-8")
        tmp.replace(self.store_path)
