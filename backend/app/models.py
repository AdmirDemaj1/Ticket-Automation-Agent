"""Domain models shared by the API, the graph and the providers."""

from typing import Literal

from pydantic import BaseModel, Field

RunStatus = Literal[
    "queued",
    "running",
    "awaiting_review",
    "creating_tickets",
    "completed",
    "failed",
    "cancelled",
]
RUN_STATUSES: tuple[RunStatus, ...] = (
    "queued",
    "running",
    "awaiting_review",
    "creating_tickets",
    "completed",
    "failed",
    "cancelled",
)

TicketType = Literal["Story", "Task", "Bug", "Sub-task"]


class Segment(BaseModel):
    speaker: str | None = None
    start_s: float | None = None
    text: str


class Transcript(BaseModel):
    title: str | None = None
    segments: list[Segment]


class ScreenshotRef(BaseModel):
    path: str
    order: int
    caption: str | None = None


class Requirement(BaseModel):
    id: str
    title: str
    detail: str
    screen: str | None = None
    source_quote: str | None = None
    priority_hint: Literal["high", "medium", "low"] | None = None


class Evidence(BaseModel):
    path: str
    start_line: int | None = None
    end_line: int | None = None
    note: str


class CodeFinding(BaseModel):
    requirement_id: str
    status: Literal["implemented", "partial", "missing", "unclear"]
    evidence: list[Evidence]
    affected_files: list[str]
    confidence: Literal["high", "medium", "low"]


class TicketDraft(BaseModel):
    temp_id: str
    type: TicketType
    title: str = Field(max_length=200)
    description: str
    acceptance_criteria: list[str]
    estimate: str | None = None
    labels: list[str]
    related_files: list[str]
    requirement_ids: list[str]
    status_in_code: Literal["new", "extends_existing", "already_done"]
    selected: bool = True


def _default_issue_types() -> list[TicketType]:
    return ["Story", "Task", "Bug"]


class RunInputs(BaseModel):
    """What the user chose for a run. Contains no secrets."""

    repo: str
    branch: str
    jira_project_key: str
    issue_types: list[TicketType] = Field(default_factory=_default_issue_types)
    sprint_id: int | None = None
