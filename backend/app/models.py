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

    repo: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    jira_project_key: str = Field(min_length=1)
    issue_types: list[TicketType] = Field(default_factory=_default_issue_types, min_length=1)
    sprint_id: int | None = None


# ---------- LLM outputs (one wrapper object per prompt) ----------


class ScreenSummary(BaseModel):
    screen: str = Field(description="Screen name, or 'Unassigned' when unclear")
    feedback: list[str]
    decisions: list[str]
    actions: list[str]
    open_questions: list[str]


class MeetingAnalysis(BaseModel):
    screens: list[ScreenSummary]
    parked: list[str] = Field(description="Items explicitly postponed or rejected")
    notes: list[str] = Field(description="Ambiguities, e.g. statements with an unclear screen")


class RequirementList(BaseModel):
    requirements: list[Requirement]


class CodePlan(BaseModel):
    paths: list[str] = Field(description="Repository paths to read, most relevant first")


class FindingList(BaseModel):
    findings: list[CodeFinding]


class TicketDraftOut(BaseModel):
    """A draft as the model writes it. Ids and selection are set by code."""

    type: TicketType
    title: str
    description: str
    acceptance_criteria: list[str]
    estimate: str | None
    labels: list[str]
    related_files: list[str]
    requirement_ids: list[str]
    status_in_code: Literal["new", "extends_existing", "already_done"]


class DraftList(BaseModel):
    drafts: list[TicketDraftOut]


# ---------- review and results ----------


class ReviewDecision(BaseModel):
    """The value the graph resumes with. Built by the API from saved drafts only."""

    decision: Literal["approve", "reject"]
    drafts: list[TicketDraft] = Field(default_factory=list)


class CreatedTicket(BaseModel):
    temp_id: str
    key: str | None = None
    url: str | None = None
    existed: bool = False
    error: str | None = None
