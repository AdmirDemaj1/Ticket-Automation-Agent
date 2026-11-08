"""Provider interfaces. Implementations: fakes (M1), GitHub/GitLab (M3), Jira (M4).

Providers are built from settings when needed and never stored in graph state.
"""

from typing import Protocol

from pydantic import BaseModel

from app.models import Transcript


class ProviderError(Exception):
    """A provider call failed in a way the user should see (message is safe to show)."""


class ProviderNotAvailable(ProviderError):
    """The configured provider is not implemented yet or not usable."""


# ---------- transcript ----------


class TranscriptProvider(Protocol):
    def load(self, source: str) -> Transcript: ...


# ---------- code ----------


class Repo(BaseModel):
    id: str  # e.g. "owner/name" (GitHub) or "group/project" (GitLab)
    name: str
    default_branch: str | None = None


class FileEntry(BaseModel):
    path: str
    size: int | None = None


class CodeProvider(Protocol):
    """Read-only access to a code host."""

    async def list_repos(self) -> list[Repo]: ...

    async def list_branches(self, repo: str) -> list[str]: ...

    async def list_tree(self, repo: str, ref: str) -> list[FileEntry]: ...

    async def get_file(self, repo: str, ref: str, path: str, max_bytes: int) -> str | None:
        """Return text content, or None if the file is binary, too large or missing."""
        ...


# ---------- jira ----------


class JiraProject(BaseModel):
    key: str
    name: str


class JiraIssueType(BaseModel):
    id: str
    name: str
    subtask: bool = False


class CreateField(BaseModel):
    id: str
    name: str
    required: bool
    has_default: bool = False


class NewIssue(BaseModel):
    """A fully validated, user-approved issue ready to create."""

    issue_type: str
    summary: str
    description: str
    labels: list[str]


class IssueRef(BaseModel):
    key: str
    url: str


class CreateOutcome(BaseModel):
    """Result for one issue; one failure must not block the others."""

    index: int
    issue: IssueRef | None = None
    error: str | None = None


class JiraProvider(Protocol):
    async def list_projects(self) -> list[JiraProject]: ...

    async def list_issue_types(self, project_key: str) -> list[JiraIssueType]: ...

    async def get_create_fields(
        self, project_key: str, issue_type_id: str
    ) -> list[CreateField]: ...

    async def find_by_label(self, label: str) -> list[IssueRef]: ...

    async def create_issues(
        self, project_key: str, issues: list[NewIssue]
    ) -> list[CreateOutcome]: ...
