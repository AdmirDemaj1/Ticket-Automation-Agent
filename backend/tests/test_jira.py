import base64
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, load_settings
from app.main import create_app
from app.models import TicketDraft
from app.providers.adf import to_adf
from app.providers.base import NewIssue, ProviderError
from app.providers.jira import JiraCloudProvider
from app.services.tickets import (
    UnfillableFields,
    assign_to_sprint,
    check_required_fields,
    create_approved_tickets,
)
from tests.conftest import FIXTURES, fixture_upload, wait_for
from tests.jira_mock import SITE, MockJira


@pytest.fixture
def jira_site() -> Iterator[MockJira]:
    mock = MockJira()
    with mock.router:
        yield mock


def _jira() -> JiraCloudProvider:
    return JiraCloudProvider(SITE, "me@example.com", "api-token", retry_wait=0)


def _draft(temp_id: str, title: str | None = None) -> TicketDraft:
    return TicketDraft.model_validate(
        {
            "temp_id": temp_id,
            "type": "Story",
            "title": title or f"Ticket {temp_id}",
            "description": "Build it.",
            "acceptance_criteria": ["Works"],
            "labels": ["onboarding"],
            "related_files": [],
            "requirement_ids": ["R1"],
            "status_in_code": "new",
        }
    )


# ---------- ADF and settings ----------


def test_adf_paragraphs_lists_and_bold_headings() -> None:
    doc = to_adf("Intro line\nsecond line\n\nAcceptance criteria:\n- one\n- two\n\nEnd.")
    assert doc["type"] == "doc" and doc["version"] == 1
    intro, heading, bullets, end = doc["content"]
    assert [n["type"] for n in intro["content"]] == ["text", "hardBreak", "text"]
    assert heading["content"][0]["marks"] == [{"type": "strong"}]
    assert bullets["type"] == "bulletList"
    items = [i["content"][0]["content"][0]["text"] for i in bullets["content"]]
    assert items == ["one", "two"]
    assert end["content"][0]["text"] == "End."


def test_adf_never_interprets_markup() -> None:
    doc = to_adf('{"type": "mention"} <b>x</b>')
    assert doc["content"][0]["content"][0]["text"] == '{"type": "mention"} <b>x</b>'
    assert to_adf("")["content"] == [{"type": "paragraph", "content": []}]


def test_jira_base_url_keeps_only_the_site(tmp_path: Path) -> None:
    s = load_settings(
        data_dir=tmp_path,
        jira_provider="jira",
        jira_base_url="https://adidemaj4.atlassian.net/jira/software/projects/A3/boards/2/backlog",
        jira_email="me@example.com",
        jira_api_token="t",
    )
    assert s.jira_base_url == "https://adidemaj4.atlassian.net"
    with pytest.raises(ConfigError, match="JIRA_BASE_URL"):
        load_settings(data_dir=tmp_path, jira_base_url="adidemaj4.atlassian.net")


# ---------- reads ----------


async def test_basic_auth_and_paged_projects(jira_site: MockJira) -> None:
    projects = await _jira().list_projects()
    assert [p.key for p in projects] == ["A3", "OPS"]
    auth = jira_site.router.calls[0].request.headers["authorization"]
    assert auth == "Basic " + base64.b64encode(b"me@example.com:api-token").decode()


async def test_issue_types_and_required_fields(jira_site: MockJira) -> None:
    types = await _jira().list_issue_types("A3")
    assert [(t.name, t.subtask) for t in types][:2] == [("Story", False), ("Task", False)]
    await check_required_fields(_jira(), "A3", ["Story", "Task"])  # reporter has a default

    jira_site.extra_required["10001"] = [
        {"fieldId": "customfield_10020", "key": "team", "name": "Team", "required": True},
        {"fieldId": "components", "key": "components", "name": "Components", "required": True},
        {
            "fieldId": "priority",
            "key": "priority",
            "name": "Priority",
            "required": True,
            "hasDefaultValue": True,
        },
    ]
    with pytest.raises(UnfillableFields) as e:
        await check_required_fields(_jira(), "A3", ["Story", "Task", "Subtask", "Epic"])
    message = str(e.value)
    assert "Story: Team, Components" in message and "Priority" not in message
    assert "Subtask: sub-tasks need a parent" in message
    assert "Epic: this issue type does not exist" in message
    assert "Task:" not in message


async def test_find_by_label_pages_with_next_token(jira_site: MockJira) -> None:
    jira = _jira()
    await jira.create_issues(
        "A3",
        [
            NewIssue(issue_type="Story", summary="a", description="d", labels=["mtj-r", "x"]),
            NewIssue(issue_type="Task", summary="b", description="d", labels=["mtj-r"]),
        ],
    )
    found = await jira.find_by_label("A3", "mtj-r")
    assert [(f.key, f.url) for f in found] == [
        ("A3-1", f"{SITE}/browse/A3-1"),
        ("A3-2", f"{SITE}/browse/A3-2"),
    ]
    assert found[0].labels == ["mtj-r", "x"]
    searches = jira_site.calls("GET", "/search/jql")
    assert searches[0].url.params["jql"] == 'project = "A3" AND labels = "mtj-r"'
    assert searches[1].url.params["nextPageToken"] == "p2"
    assert not jira_site.calls("GET", "/rest/api/3/search")[0].url.path.endswith("/search")


async def test_sprints_from_scrum_boards_only(jira_site: MockJira) -> None:
    sprints = await _jira().list_sprints("A3")
    assert [(s.id, s.state, s.board) for s in sprints] == [
        (6, "active", "A3 board"),
        (7, "future", "A3 board"),
    ]


# ---------- writes ----------


async def test_bulk_create_maps_partial_failures(jira_site: MockJira) -> None:
    jira_site.fail_summaries = {"bad"}
    outcomes = await _jira().create_issues(
        "A3",
        [
            NewIssue(issue_type="Story", summary="ok 1", description="d", labels=[]),
            NewIssue(issue_type="Story", summary="bad", description="d", labels=[]),
            NewIssue(issue_type="Epic", summary="no type", description="d", labels=[]),
            NewIssue(issue_type="Task", summary="ok 2", description="- a\n- b", labels=["l"]),
        ],
    )
    assert [(o.issue.key if o.issue else None) for o in outcomes] == ["A3-1", None, None, "A3-2"]
    assert outcomes[1].error == "summary: Summary is not allowed"
    assert outcomes[2].error and "does not exist in A3" in outcomes[2].error
    sent = json.loads(jira_site.calls("POST", "/issue/bulk")[0].content)["issueUpdates"]
    assert len(sent) == 3  # the unknown type never left the app
    fields = sent[2]["fields"]
    assert fields["issuetype"] == {"id": "10002"} and fields["project"] == {"key": "A3"}
    assert fields["description"]["content"][0]["type"] == "bulletList"


async def test_all_failing_bulk_returns_errors_not_exceptions(jira_site: MockJira) -> None:
    jira_site.fail_summaries = {"bad"}
    outcomes = await _jira().create_issues(
        "A3", [NewIssue(issue_type="Story", summary="bad", description="d", labels=[])]
    )
    assert outcomes[0].issue is None and outcomes[0].error


async def test_server_errors_on_create_are_not_retried(jira_site: MockJira) -> None:
    jira_site.bulk_status = 500
    with pytest.raises(ProviderError, match="approving again is safe"):
        await _jira().create_issues(
            "A3", [NewIssue(issue_type="Story", summary="x", description="d", labels=[])]
        )
    assert len(jira_site.calls("POST", "/issue/bulk")) == 1


async def test_rate_limited_create_is_retried() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"issueTypes": [{"id": "1", "name": "Story"}]})
        if calls.count("POST") == 1:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(201, json={"issues": [{"key": "A3-9"}], "errors": []})

    jira = JiraCloudProvider(SITE, "e", "t", transport=httpx.MockTransport(handler), retry_wait=0)
    outcomes = await jira.create_issues(
        "A3", [NewIssue(issue_type="Story", summary="x", description="d", labels=[])]
    )
    assert outcomes[0].issue and outcomes[0].issue.key == "A3-9"
    assert calls.count("POST") == 2


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "rejected JIRA_EMAIL"), (403, "lacks permission"), (404, "could not find")],
)
async def test_readable_errors(status: int, message: str) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(status, json={}))
    jira = JiraCloudProvider(SITE, "e", "t", transport=transport, retry_wait=0)
    with pytest.raises(ProviderError, match=message):
        await jira.list_projects()


# ---------- the shared ticket service against the real provider ----------


async def test_approving_twice_creates_no_duplicates(jira_site: MockJira) -> None:
    drafts = [_draft("T1"), _draft("T2")]
    first = await create_approved_tickets(_jira(), "A3", "run1", drafts)
    second = await create_approved_tickets(_jira(), "A3", "run1", drafts)
    assert [c.key for c in first] == ["A3-1", "A3-2"]
    assert [(c.key, c.existed) for c in second] == [("A3-1", True), ("A3-2", True)]
    assert len(jira_site.issues) == 2
    assert "mtj-run1-T2" in jira_site.issues[1]["labels"]


async def test_one_failure_is_reported_and_retry_creates_only_the_rest(
    jira_site: MockJira,
) -> None:
    jira_site.fail_summaries = {"Ticket T2"}
    drafts = [_draft("T1"), _draft("T2"), _draft("T3")]
    first = await create_approved_tickets(_jira(), "A3", "run1", drafts)
    assert [c.error is None for c in first] == [True, False, True]
    jira_site.fail_summaries = set()
    second = await create_approved_tickets(_jira(), "A3", "run1", drafts)
    assert [(c.temp_id, c.existed) for c in second] == [("T1", True), ("T2", False), ("T3", True)]
    assert len(jira_site.issues) == 3


async def test_sprint_assignment_and_failure(jira_site: MockJira) -> None:
    created = await create_approved_tickets(_jira(), "A3", "r", [_draft("T1"), _draft("T2")])
    ok = await assign_to_sprint(_jira(), 6, created)
    assert ok.added == ["A3-1", "A3-2"] and ok.error is None
    assert jira_site.sprint_issues[6] == ["A3-1", "A3-2"]
    bad = await assign_to_sprint(_jira(), 99, created)
    assert bad.added == [] and bad.error and "stay in the backlog" in bad.error


def test_full_run_with_jira_cloud(tmp_path: Path) -> None:
    settings = load_settings(
        data_dir=tmp_path / "data",
        fixtures_dir=FIXTURES,
        jira_provider="jira",
        jira_base_url=SITE,
        jira_email="me@example.com",
        jira_api_token="api-token",
    )
    mock = MockJira()
    with mock.router, TestClient(create_app(settings)) as client:
        assert [s["id"] for s in client.get("/jira/projects/A3/sprints").json()] == [6, 7]
        res = client.post(
            "/runs",
            data={
                "inputs": json.dumps(
                    {"repo": "fixtures/demo-app", "branch": "main", "jira_project_key": "A3"}
                ),
            },
            files=fixture_upload(),
        )
        assert res.status_code == 202, res.text
        run_id = res.json()["run_id"]
        assert wait_for(client, run_id)["review_stage"] == "drafts"

        res = client.post(
            f"/runs/{run_id}/approve", json={"selected": ["T1", "T2"], "sprint_id": 6}
        )
        assert res.status_code == 202
        done = wait_for(client, run_id, ("completed", "failed"))
        assert done["run"]["status"] == "completed", done["run"]["error"]
        assert [c["key"] for c in done["created"]] == ["A3-1", "A3-2"]
        assert done["sprint"] == {"sprint_id": 6, "added": ["A3-1", "A3-2"], "error": None}
        assert mock.issues[0]["description"]["type"] == "doc"
        assert f"mtj-{run_id}" in mock.issues[0]["labels"]


def test_unfillable_fields_fail_before_the_run_starts(tmp_path: Path) -> None:
    settings = load_settings(
        data_dir=tmp_path / "data",
        fixtures_dir=FIXTURES,
        jira_provider="jira",
        jira_base_url=SITE,
        jira_email="me@example.com",
        jira_api_token="api-token",
    )
    mock = MockJira()
    mock.extra_required["10001"] = [
        {"fieldId": "customfield_1", "key": "team", "name": "Team", "required": True}
    ]
    with mock.router, TestClient(create_app(settings)) as client:
        res = client.post(
            "/runs",
            data={
                "inputs": json.dumps(
                    {"repo": "fixtures/demo-app", "branch": "main", "jira_project_key": "A3"}
                ),
                "transcript_text": "Anna: add CSV export.\nMarco: yes.\nAnna: ok.",
            },
        )
        assert res.status_code == 400
        assert "Story: Team" in res.json()["detail"]
        assert client.get("/runs").json() == []
        assert mock.calls("POST", "/issue/bulk") == []
