import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.main import create_app
from app.providers.base import ProviderError
from app.providers.code_github import GitHubCodeProvider, ReadOnlyViolation, _only_get
from tests.conftest import FIXTURES, fixture_upload, wait_for
from tests.github_mock import ALLOWED_PATHS, API, REPO, MockGitHub


@pytest.fixture
def gh() -> Iterator[MockGitHub]:
    mock = MockGitHub(FIXTURES / "repo")
    with mock.router:
        yield mock


def _provider(max_file_bytes: int = 200_000) -> GitHubCodeProvider:
    return GitHubCodeProvider(
        "github_pat_test", api_url=API, max_file_bytes=max_file_bytes, retry_wait=0
    )


async def test_repos_paginate_and_skip_archived(gh: MockGitHub) -> None:
    repos = await _provider().list_repos()
    assert [(r.id, r.default_branch) for r in repos] == [(REPO, "main")]
    first = gh.router.calls[0].request
    assert first.headers["authorization"] == "Bearer github_pat_test"
    assert first.headers["x-github-api-version"] == "2022-11-28"
    assert len(gh.router.calls) == 2  # followed the Link header


async def test_branches(gh: MockGitHub) -> None:
    assert await _provider().list_branches(REPO) == ["main", "feature/x"]
    with pytest.raises(ProviderError, match="owner/name"):
        await _provider().list_branches("not a repo")


async def test_tree_resolves_branch_and_filters(gh: MockGitHub) -> None:
    paths = [e.path for e in await _provider().list_tree(REPO, "feature/x")]
    assert "src/pages/Login.tsx" in paths
    assert "package-lock.json" not in paths  # lockfile
    assert "public/logo.png" not in paths  # binary
    assert all(not p.endswith("/") for p in paths)
    assert f"/repos/{REPO}/git/ref/heads/feature/x" in gh.paths()


async def test_tree_drops_files_over_the_size_limit(gh: MockGitHub) -> None:
    paths = [e.path for e in await _provider(max_file_bytes=500).list_tree(REPO, "main")]
    assert "src/api/auth.ts" in paths  # 386 bytes
    assert "src/pages/Login.tsx" not in paths  # 1297 bytes


async def test_truncated_tree_is_walked_per_directory() -> None:
    mock = MockGitHub(FIXTURES / "repo", truncate=True)
    with mock.router:
        paths = [e.path for e in await _provider().list_tree(REPO, "main")]
    assert {"src/pages/Login.tsx", "src/api/orders.ts", "README.md"} <= set(paths)


async def test_get_file(gh: MockGitHub) -> None:
    p = _provider()
    text = await p.get_file(REPO, "main", "src/api/auth.ts", 10_000)
    assert text is not None and "Invalid email or password" in text
    assert await p.get_file(REPO, "main", "src/api/auth.ts", 100) is None  # too large
    assert await p.get_file(REPO, "main", "public/logo.png", 1_000_000) is None  # binary
    assert await p.get_file(REPO, "main", "nope.ts", 10_000) is None  # missing
    assert await p.get_file(REPO, "main", "../secrets", 10_000) is None
    contents = [c.request for c in gh.router.calls if "/contents/" in c.request.url.path]
    assert contents[0].url.params["ref"] == "main"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401, json={}), "rejected GITHUB_TOKEN"),
        (
            httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}),
            "rate limit reached",
        ),
        (httpx.Response(403, json={}), "Contents: Read-only"),
        (httpx.Response(404, json={}), "token has no access"),
        (httpx.Response(409, json={}), "repository is empty"),
    ],
)
async def test_errors_are_readable(response: httpx.Response, message: str) -> None:
    with httpx.MockTransport(lambda _: response) as transport:
        p = GitHubCodeProvider("t", api_url=API, transport=transport, retry_wait=0)
        with pytest.raises(ProviderError, match=message):
            await p.list_branches(REPO)


async def test_transient_errors_are_retried_three_times() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(502)
        return httpx.Response(200, json=[{"name": "main"}])

    p = GitHubCodeProvider("t", api_url=API, transport=httpx.MockTransport(handler), retry_wait=0)
    assert await p.list_branches(REPO) == ["main"]
    assert len(calls) == 3

    always_down = httpx.MockTransport(lambda _: httpx.Response(503))
    p = GitHubCodeProvider("t", api_url=API, transport=always_down, retry_wait=0)
    with pytest.raises(ProviderError, match=r"HTTP 503 .* after 3 tries"):
        await p.list_branches(REPO)


async def test_non_get_requests_are_refused_before_sending() -> None:
    with pytest.raises(ReadOnlyViolation):
        await _only_get(httpx.Request("POST", f"{API}/repos/{REPO}/git/refs"))
    await _only_get(httpx.Request("GET", f"{API}/user/repos"))


def test_full_run_against_github_makes_only_read_calls(tmp_path: Path) -> None:
    """Spec 6.2 / M3: the whole pipeline uses only GET on read endpoints."""
    settings: Settings = load_settings(
        data_dir=tmp_path / "data",
        fixtures_dir=FIXTURES,
        code_provider="github",
        github_token="github_pat_test",
        github_api_url=API,
    )
    mock = MockGitHub(FIXTURES / "repo")
    with mock.router, TestClient(create_app(settings)) as client:
        assert [r["id"] for r in client.get("/code/repos").json()] == [REPO]
        res = client.post(
            "/runs",
            data={
                "inputs": json.dumps({"repo": REPO, "branch": "main", "jira_project_key": "DEMO"})
            },
            files=fixture_upload(),
        )
        assert res.status_code == 202, res.text
        detail = wait_for(client, res.json()["run_id"])
        assert detail["run"]["status"] == "awaiting_review", detail["run"]["error"]
        assert "src/pages/Login.tsx" in detail["files_read"]

        # Checked inside the block: respx clears its call log when the mock closes.
        assert len(mock.router.calls) > 5
        assert mock.methods() == {"GET"}
        unexpected = [p for p in mock.paths() if not ALLOWED_PATHS.match(p)]
        assert unexpected == []
        assert not any("/search/" in p for p in mock.paths())
