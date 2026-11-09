"""Create approved drafts in Jira, idempotently. Shared by the fake and the real Jira provider.

Every issue gets two labels: `mtj-<run_id>` and `mtj-<run_id>-<temp_id>`. Before creating,
each draft's own label is searched; drafts that already exist are reported, not re-created.
Approving the same run twice therefore never makes duplicates.
"""

import re

from app.models import CreatedTicket, TicketDraft
from app.providers.base import JiraProvider, NewIssue, ProviderError

CHUNK_SIZE = 50
_LABEL_UNSAFE = re.compile(r"[^\w.-]+")


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


async def create_approved_tickets(
    jira: JiraProvider, project_key: str, run_id: str, drafts: list[TicketDraft]
) -> list[CreatedTicket]:
    results: dict[str, CreatedTicket] = {}
    pending: list[TicketDraft] = []
    for draft in drafts:
        try:
            existing = await jira.find_by_label(draft_label(run_id, draft.temp_id))
        except ProviderError as e:
            results[draft.temp_id] = CreatedTicket(temp_id=draft.temp_id, error=str(e))
            continue
        if existing:
            results[draft.temp_id] = CreatedTicket(
                temp_id=draft.temp_id, key=existing[0].key, url=existing[0].url, existed=True
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
