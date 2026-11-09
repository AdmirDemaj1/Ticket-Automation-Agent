from pathlib import Path

import pytest

from app.providers.base import NewIssue, ProviderError
from app.providers.fakes import FAKE_REPO_ID, FakeCodeProvider, FakeJiraProvider
from tests.conftest import FIXTURES

REPO = FIXTURES / "repo"


@pytest.fixture
def code() -> FakeCodeProvider:
    return FakeCodeProvider(REPO, max_bytes=200_000)


async def test_fake_code_lists_repo_and_branch(code: FakeCodeProvider) -> None:
    repos = await code.list_repos()
    assert [r.id for r in repos] == [FAKE_REPO_ID]
    assert await code.list_branches(FAKE_REPO_ID) == ["main"]


async def test_fake_code_tree_skips_noise(code: FakeCodeProvider) -> None:
    paths = {e.path for e in await code.list_tree(FAKE_REPO_ID, "main")}
    assert {"src/pages/Login.tsx", "src/pages/Dashboard.tsx", "src/api/orders.ts"} <= paths
    assert "package-lock.json" not in paths
    assert "public/logo.png" not in paths


async def test_fake_code_get_file(code: FakeCodeProvider) -> None:
    text = await code.get_file(FAKE_REPO_ID, "main", "src/pages/Login.tsx", 200_000)
    assert text is not None and "showPassword" in text
    assert await code.get_file(FAKE_REPO_ID, "main", "public/logo.png", 200_000) is None
    assert await code.get_file(FAKE_REPO_ID, "main", "src/pages/Login.tsx", 10) is None
    assert await code.get_file(FAKE_REPO_ID, "main", "missing.ts", 200_000) is None


async def test_fake_code_blocks_path_traversal(code: FakeCodeProvider) -> None:
    assert await code.get_file(FAKE_REPO_ID, "main", "../transcript.vtt", 200_000) is None
    assert await code.get_file(FAKE_REPO_ID, "main", "/etc/hosts", 200_000) is None


async def test_fake_code_rejects_unknown_repo_or_branch(code: FakeCodeProvider) -> None:
    with pytest.raises(ProviderError):
        await code.list_tree("other/repo", "main")
    with pytest.raises(ProviderError):
        await code.list_tree(FAKE_REPO_ID, "develop")


async def test_fake_jira_creates_searches_and_persists(tmp_path: Path) -> None:
    store = tmp_path / "fake_jira.json"
    jira = FakeJiraProvider(store)
    outcomes = await jira.create_issues(
        "DEMO",
        [
            NewIssue(
                issue_type="Story", summary="A", description="d", labels=["mtj-r1", "mtj-r1-T1"]
            ),
            NewIssue(
                issue_type="Task", summary="B", description="d", labels=["mtj-r1", "mtj-r1-T2"]
            ),
        ],
    )
    assert [o.issue.key for o in outcomes if o.issue] == ["DEMO-1", "DEMO-2"]

    reopened = FakeJiraProvider(store)  # survives a backend restart
    assert [r.key for r in await reopened.find_by_label("DEMO", "mtj-r1")] == ["DEMO-1", "DEMO-2"]
    assert [r.key for r in await reopened.find_by_label("DEMO", "mtj-r1-T2")] == ["DEMO-2"]
    assert await reopened.find_by_label("DEMO", "mtj-other") == []
    assert [name for name, _ in jira.calls] == ["create_issues"]


async def test_fake_jira_unknown_project(tmp_path: Path) -> None:
    jira = FakeJiraProvider(tmp_path / "j.json")
    with pytest.raises(ProviderError):
        await jira.list_issue_types("NOPE")
