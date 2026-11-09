from pathlib import Path

from app.models import TicketDraft
from app.providers.base import CreateOutcome, NewIssue, ProviderError
from app.providers.fakes import FakeJiraProvider
from app.services.tickets import (
    CHUNK_SIZE,
    clean_label,
    create_approved_tickets,
    issue_description,
    to_new_issue,
)


def _draft(temp_id: str, **kw: object) -> TicketDraft:
    data: dict[str, object] = {
        "temp_id": temp_id,
        "type": "Story",
        "title": f"Ticket {temp_id}",
        "description": "Build it.",
        "acceptance_criteria": ["Works"],
        "labels": ["Login screen"],
        "related_files": ["src/a.ts"],
        "requirement_ids": ["R1"],
        "status_in_code": "new",
    }
    data.update(kw)
    return TicketDraft.model_validate(data)


def test_new_issue_labels_and_description() -> None:
    issue = to_new_issue("run1", _draft("T1"))
    assert issue.labels == ["Login-screen", "mtj-run1", "mtj-run1-T1"]
    text = issue_description(_draft("T1", estimate="3d"))
    assert "Acceptance criteria:\n- Works" in text
    assert "Related files:\n- src/a.ts" in text and "Estimate: 3d" in text
    assert clean_label("  a b/c  ") == "a-b-c"


async def test_approving_twice_creates_no_duplicates(tmp_path: Path) -> None:
    jira = FakeJiraProvider(tmp_path / "jira.json")
    drafts = [_draft("T1"), _draft("T2")]
    first = await create_approved_tickets(jira, "DEMO", "run1", drafts)
    second = await create_approved_tickets(jira, "DEMO", "run1", drafts)
    assert [c.key for c in first] == ["DEMO-1", "DEMO-2"]
    assert [(c.key, c.existed) for c in second] == [("DEMO-1", True), ("DEMO-2", True)]
    assert len(jira.stored_issues()) == 2


class FlakyJira(FakeJiraProvider):
    """Fails one issue in each batch and records batch sizes."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.batches: list[int] = []

    async def create_issues(self, project_key: str, issues: list[NewIssue]) -> list[CreateOutcome]:
        self.batches.append(len(issues))
        ok = await super().create_issues(project_key, issues[1:])
        shifted = [o.model_copy(update={"index": o.index + 1}) for o in ok]
        return [CreateOutcome(index=0, error="Summary is too long"), *shifted]


async def test_one_failure_does_not_block_the_rest_and_chunks_of_50(tmp_path: Path) -> None:
    jira = FlakyJira(tmp_path / "jira.json")
    drafts = [_draft(f"T{i}") for i in range(1, CHUNK_SIZE + 6)]
    result = await create_approved_tickets(jira, "DEMO", "run1", drafts)
    assert jira.batches == [CHUNK_SIZE, 5]
    errors = [c.temp_id for c in result if c.error]
    assert errors == ["T1", f"T{CHUNK_SIZE + 1}"]
    assert sum(1 for c in result if c.key) == len(drafts) - 2


class DownJira(FakeJiraProvider):
    async def create_issues(self, project_key: str, issues: list[NewIssue]) -> list[CreateOutcome]:
        raise ProviderError("Jira is unavailable")


async def test_provider_errors_are_reported_per_ticket(tmp_path: Path) -> None:
    result = await create_approved_tickets(
        DownJira(tmp_path / "j.json"), "DEMO", "r", [_draft("T1")]
    )
    assert result[0].error == "Jira is unavailable" and result[0].key is None
