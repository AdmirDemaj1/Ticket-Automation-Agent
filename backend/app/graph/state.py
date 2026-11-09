"""Graph state. Checkpointed to SQLite after every node, so it holds no secrets or tokens.

Values are plain JSON types (dicts and lists), not Pydantic objects: that keeps checkpoints
readable and avoids the checkpointer's deserialization allowlist for custom classes. Nodes
validate into the models in `app.models` when they read.
"""

from typing import Any, TypedDict


class RunState(TypedDict, total=False):
    run_id: str
    inputs: dict[str, Any]  # RunInputs
    transcript_path: str  # stored upload under data/runs/<run_id>/
    transcript: dict[str, Any] | None  # Transcript
    screenshots: list[dict[str, Any]]  # ScreenshotRef, in the user's order
    meeting_analysis: dict[str, Any] | None  # MeetingAnalysis
    requirements: list[dict[str, Any]]  # Requirement
    code_candidates: list[str]
    code_files: dict[str, str]  # path -> text that was read (local data only)
    code_findings: list[dict[str, Any]]  # CodeFinding
    drafts: list[dict[str, Any]]  # TicketDraft
    review: dict[str, Any] | None  # ReviewDecision, set on resume
    created: list[dict[str, Any]]  # CreatedTicket
    tokens_used: int
    errors: list[str]
