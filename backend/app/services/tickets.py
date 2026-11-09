"""Create approved drafts in Jira, idempotently. Shared by the fake and the real Jira provider.

Every issue gets two labels: `mtj-<run_id>` and `mtj-<run_id>-<temp_id>`. Before creating,
the run's label is searched once, and drafts whose own label is found (or whose Jira key is
already stored locally, which covers search lag) are reported as existing, not re-created.
Approving the same run twice therefore never makes duplicates.
"""

import re
from dataclasses import dataclass

from app.models import CreatedTicket, TicketDraft
from app.providers.base import IssueRef, JiraProvider, NewIssue, ProviderError

CHUNK_SIZE = 50
_LABEL_UNSAFE = re.compile(r"[^\w.-]+")

# Fields the app always fills (or Jira fills itself) when creating an issue.
FILLED_FIELDS = frozenset({"summary", "issuetype", "project", "description", "labels", "reporter"})


class UnfillableFields(ProviderError):
    """The project requires fields the app cannot fill. The message lists them."""


@dataclass(frozen=True)
class SprintResult:
    sprint_id: int
    added: list[str]
    error: str | None = None


def run_label(run_id: str) -> str:
    return f"mtj-{run_id}"


def draft_label(run_id: str, temp_id: str) -> str:
    return f"mtj-{run_id}-{temp_id}"


def clean_label(label: str) -> str:
    """Jira labels cannot contain spaces."""
    return _LABEL_UNSAFE.sub("-", label.strip()).strip("-")[:255]


def issue_description(draft: TicketDraft) -> str:
    parts = [draft.description.strip()]
    if draft.acceptance_criteria:
        parts.append(
            "Acceptance criteria:\n" + "\n".join(f"- {c}" for c in draft.acceptance_criteria)
        )
    if draft.related_files:
        parts.append("Related files:\n" + "\n".join(f"- {f}" for f in draft.related_files))
    if draft.estimate:
        parts.append(f"Estimate: {draft.estimate}")
    if draft.requirement_ids:
        parts.append("Meeting requirements: " + ", ".join(draft.requirement_ids))
    return "\n\n".join(p for p in parts if p)


def to_new_issue(run_id: str, draft: TicketDraft) -> NewIssue:
    labels = [clean_label(lbl) for lbl in draft.labels]
    labels += [run_label(run_id), draft_label(run_id, draft.temp_id)]
    unique = list(dict.fromkeys(lbl for lbl in labels if lbl))
    return NewIssue(
        issue_type=draft.type,
        summary=draft.title.strip()[:200],
        description=issue_description(draft),
        labels=unique,
    )


async def check_required_fields(
    jira: JiraProvider, project_key: str, type_names: list[str]
) -> None:
    """Raise UnfillableFields listing required fields (per issue type) the app cannot fill."""
    types = {t.name: t for t in await jira.list_issue_types(project_key)}
    problems: list[str] = []
    for name in dict.fromkeys(type_names):
        issue_type = types.get(name)
        if issue_type is None:
            problems.append(f"{name}: this issue type does not exist in {project_key}")
            continue
        if issue_type.subtask:
            problems.append(f"{name}: sub-tasks need a parent issue, which the app does not set")
            continue
        fields = await jira.get_create_fields(project_key, issue_type.id)
        missing = [
            f.name for f in fields if f.required and not f.has_default and f.id not in FILLED_FIELDS
        ]
        if missing:
            problems.append(f"{name}: {', '.join(missing)}")
    if problems:
        raise UnfillableFields(
            f"Jira project {project_key} requires fields this app cannot fill. "
            "Make them optional or give them a default in Jira, or choose other issue types. "
            + " | ".join(problems)
        )


async def create_approved_tickets(
    jira: JiraProvider,
    project_key: str,
    run_id: str,
    drafts: list[TicketDraft],
    known: dict[str, IssueRef] | None = None,
) -> list[CreatedTicket]:
    """Create the drafts that do not exist yet. One failure never blocks the others."""
    results: dict[str, CreatedTicket] = {}
    existing = dict(known or {})
    try:
        for ref in await jira.find_by_label(project_key, run_label(run_id)):
            for draft in drafts:
                if draft_label(run_id, draft.temp_id) in ref.labels:
                    existing.setdefault(draft.temp_id, ref)
    except ProviderError as e:
        # Without the search we cannot rule out duplicates for drafts not stored locally.
        for d in drafts:
            if d.temp_id not in existing:
                results[d.temp_id] = CreatedTicket(
                    temp_id=d.temp_id, error=f"Could not check for existing issues: {e}"
                )

    pending: list[TicketDraft] = []
    for draft in drafts:
        if draft.temp_id in results:
            continue
        found = existing.get(draft.temp_id)
        if found is not None:
            results[draft.temp_id] = CreatedTicket(
                temp_id=draft.temp_id, key=found.key, url=found.url, existed=True
            )
        else:
            pending.append(draft)

    for start in range(0, len(pending), CHUNK_SIZE):
        chunk = pending[start : start + CHUNK_SIZE]
        try:
            outcomes = await jira.create_issues(
                project_key, [to_new_issue(run_id, d) for d in chunk]
            )
        except ProviderError as e:
            for d in chunk:
                results[d.temp_id] = CreatedTicket(temp_id=d.temp_id, error=str(e))
            continue
        by_index = {o.index: o for o in outcomes}
        for index, d in enumerate(chunk):
            outcome = by_index.get(index)
            if outcome is None:
                results[d.temp_id] = CreatedTicket(temp_id=d.temp_id, error="No result from Jira")
            elif outcome.issue is not None:
                results[d.temp_id] = CreatedTicket(
                    temp_id=d.temp_id, key=outcome.issue.key, url=outcome.issue.url
                )
            else:
                results[d.temp_id] = CreatedTicket(
                    temp_id=d.temp_id, error=outcome.error or "Unknown error"
                )

    return [results[d.temp_id] for d in drafts]


async def assign_to_sprint(
    jira: JiraProvider, sprint_id: int, created: list[CreatedTicket]
) -> SprintResult:
    """Add created (or existing) issues to the sprint. Failure leaves them in the backlog."""
    keys = [c.key for c in created if c.key]
    added: list[str] = []
    for start in range(0, len(keys), CHUNK_SIZE):
        chunk = keys[start : start + CHUNK_SIZE]
        try:
            await jira.add_to_sprint(sprint_id, chunk)
        except ProviderError as e:
            return SprintResult(
                sprint_id=sprint_id,
                added=added,
                error=f"{e}. The remaining issues stay in the backlog.",
            )
        added.extend(chunk)
    return SprintResult(sprint_id=sprint_id, added=added)
