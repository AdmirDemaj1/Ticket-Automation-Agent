"""The run API end to end with fake providers and the fake LLM."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.fakes import FakeJiraProvider
from tests.conftest import DEMO_INPUTS, FIXTURES, start_fixture_run, wait_for


def _drafts(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return [d["draft"] for d in detail["drafts"]]


def test_full_run_review_edit_approve(client: TestClient, settings: Settings) -> None:
    run_id = start_fixture_run(client)
    detail = wait_for(client, run_id)
    assert detail["run"]["status"] == "awaiting_review", detail["run"]["error"]
    assert detail["transcript_title"]
    assert [s["caption"] for s in detail["screenshots"]] == ["Login", "Dashboard"]
    assert len(detail["requirements"]) == 6
    assert all(f["evidence"] for f in detail["code_findings"])
    assert detail["files_read"]
    assert detail["tokens_used"] > 0
    assert detail["jira_labels"][0] == f"mtj-{run_id}"

    shot = client.get(detail["screenshots"][0]["url"])
    assert shot.status_code == 200 and shot.content.startswith(b"\x89PNG")

    drafts = _drafts(detail)
    drafts[0]["title"] = "Edited title"
    res = client.put(f"/runs/{run_id}/drafts", json={"drafts": [drafts[0]]})
    assert res.status_code == 200
    assert res.json()[0]["edited"] is True and res.json()[1]["edited"] is False

    res = client.post(f"/runs/{run_id}/approve", json={"selected": ["T1", "T3"]})
    assert res.status_code == 202
    done = wait_for(client, run_id, ("completed", "failed", "cancelled"))
    assert done["run"]["status"] == "completed"
    assert [c["temp_id"] for c in done["created"]] == ["T1", "T3"]
    issues = FakeJiraProvider(settings.data_dir / "fake_jira.json").stored_issues()
    assert issues[0]["summary"] == "Edited title"
    by_id = {d["draft"]["temp_id"]: d for d in done["drafts"]}
    assert by_id["T1"]["jira_key"] and by_id["T2"]["jira_key"] is None

    # A second approval is refused: the run is no longer awaiting review.
    assert client.post(f"/runs/{run_id}/approve", json={"selected": ["T2"]}).status_code == 409


def test_restart_while_awaiting_review_then_approve(settings: Settings) -> None:
    with TestClient(create_app(settings)) as first:
        run_id = start_fixture_run(first)
        assert wait_for(first, run_id)["run"]["status"] == "awaiting_review"

    with TestClient(create_app(settings)) as second:
        detail = second.get(f"/runs/{run_id}").json()
        assert detail["run"]["status"] == "awaiting_review"
        assert len(detail["drafts"]) == 6
        res = second.post(f"/runs/{run_id}/approve", json={"selected": ["T1"]})
        assert res.status_code == 202
        done = wait_for(second, run_id, ("completed", "failed"))
        assert done["run"]["status"] == "completed"
        assert done["created"][0]["key"] == "DEMO-1"


def test_reject(client: TestClient, settings: Settings) -> None:
    run_id = start_fixture_run(client)
    wait_for(client, run_id)
    assert client.post(f"/runs/{run_id}/reject").status_code == 202
    assert wait_for(client, run_id, ("cancelled",))["created"] == []
    assert not (settings.data_dir / "fake_jira.json").exists()


def test_cancel_while_awaiting_review(client: TestClient) -> None:
    run_id = start_fixture_run(client)
    wait_for(client, run_id)
    assert client.post(f"/runs/{run_id}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/runs/{run_id}/approve", json={"selected": ["T1"]}).status_code == 409


def test_approve_validation(client: TestClient) -> None:
    run_id = start_fixture_run(client)
    wait_for(client, run_id)
    assert client.post(f"/runs/{run_id}/approve", json={"selected": []}).status_code == 400
    res = client.post(f"/runs/{run_id}/approve", json={"selected": ["T1", "T99"]})
    assert res.status_code == 400 and "T99" in res.json()["detail"]
    drafts = _drafts(client.get(f"/runs/{run_id}").json())
    bad = {**drafts[0], "temp_id": "T42"}
    assert client.put(f"/runs/{run_id}/drafts", json={"drafts": [bad]}).status_code == 400


def test_events_stream_replays_and_ends(client: TestClient) -> None:
    run_id = start_fixture_run(client)
    wait_for(client, run_id)
    client.post(f"/runs/{run_id}/reject")
    wait_for(client, run_id, ("cancelled",))

    with client.stream("GET", f"/runs/{run_id}/events") as res:
        assert res.headers["content-type"].startswith("text/event-stream")
        body = "".join(res.iter_text())
    ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    assert ids == sorted(ids) and len(ids) > 10
    assert "event: end" in body and '"status": "cancelled"' in body
    payloads = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: {")]
    steps = {p["step"] for p in payloads if "step" in p}
    assert {"load_transcript", "draft_tickets", "review", "run"} <= steps

    # Last-Event-ID: only newer events are sent after a reconnect.
    with client.stream(
        "GET", f"/runs/{run_id}/events", headers={"Last-Event-ID": str(ids[-2])}
    ) as res:
        again = "".join(res.iter_text())
    assert [int(line[4:]) for line in again.splitlines() if line.startswith("id: ")] == [ids[-1]]


@pytest.mark.parametrize(
    ("data", "files", "message"),
    [
        ({"inputs": json.dumps(DEMO_INPUTS)}, None, "either a transcript file or pasted text"),
        (
            {"inputs": json.dumps({**DEMO_INPUTS, "branch": "dev"}), "transcript_text": "A: hi"},
            None,
            "Branch 'dev' not found",
        ),
        (
            {
                "inputs": json.dumps({**DEMO_INPUTS, "issue_types": ["Epic"]}),
                "transcript_text": "x",
            },
            None,
            "Invalid run settings",
        ),
        (
            {"inputs": json.dumps(DEMO_INPUTS), "transcript_text": "x"},
            [("screenshots", ("evil.png", b"<script>alert(1)</script>", "image/png"))],
            "not a PNG, JPEG or WebP",
        ),
        (
            {"inputs": json.dumps(DEMO_INPUTS)},
            [("transcript_file", ("notes.pdf", b"%PDF-1.7", "application/pdf"))],
            "Transcript must be one of",
        ),
    ],
)
def test_upload_validation(
    client: TestClient, data: dict[str, str], files: Any, message: str
) -> None:
    res = client.post("/runs", data=data, files=files)
    assert res.status_code == 400, res.text
    assert message in res.json()["detail"]
    assert client.get("/runs").json() == []  # nothing was stored


def test_too_many_screenshots(client: TestClient, settings: Settings) -> None:
    png = (FIXTURES / "screenshots/01-login.png").read_bytes()
    files = [("screenshots", (f"{i}.png", png, "image/png")) for i in range(11)]
    res = client.post(
        "/runs", data={"inputs": json.dumps(DEMO_INPUTS), "transcript_text": "x"}, files=files
    )
    assert res.status_code == 400 and "At most 10" in res.json()["detail"]


def test_pasted_text_run(client: TestClient) -> None:
    res = client.post(
        "/runs",
        data={
            "inputs": json.dumps(DEMO_INPUTS),
            "transcript_text": "Anna: Add CSV export.\nMarco: Agreed.\nAnna: Thanks.",
        },
    )
    assert res.status_code == 202
    detail = wait_for(client, res.json()["run_id"])
    assert detail["run"]["status"] == "awaiting_review"
    assert detail["screenshots"] == []


def test_failed_run_is_reported_and_can_be_retried(settings: Settings) -> None:
    from app.llm import FakeLLM, LLMError

    llm = FakeLLM(FIXTURES / "llm", overrides={"compare_with_code": LLMError("boom (safe)")})
    with TestClient(create_app(settings, llm=llm)) as c:
        run_id = start_fixture_run(c)
        detail = wait_for(c, run_id)
        assert detail["run"]["status"] == "failed"
        assert detail["run"]["error"] == "boom (safe)"
        assert detail["requirements"]  # earlier steps are kept in the checkpoint

        del llm.overrides["compare_with_code"]
        calls_before = len(llm.calls)
        assert c.post(f"/runs/{run_id}/retry").status_code == 202
        assert wait_for(c, run_id)["run"]["status"] == "awaiting_review"
        # Retry resumed at the failed step instead of starting over.
        assert [call.step for call in llm.calls[calls_before:]] == [
            "compare_with_code",
            "draft_tickets",
        ]


def test_unexpected_errors_are_not_shown_verbatim(settings: Settings) -> None:
    from app.llm import FakeLLM

    secret = RuntimeError("const apiKey = 'leaked-from-source'")
    llm = FakeLLM(FIXTURES / "llm", overrides={"analyze_meeting": secret})
    with TestClient(create_app(settings, llm=llm)) as c:
        detail = wait_for(c, start_fixture_run(c))
    assert detail["run"]["status"] == "failed"
    assert "leaked" not in detail["run"]["error"]
    assert "RuntimeError" in detail["run"]["error"]


def test_estimate(client: TestClient) -> None:
    small = client.get("/runs/estimate?transcript_chars=1000&screenshots=0").json()
    big = client.get("/runs/estimate?transcript_chars=100000&screenshots=4").json()
    assert 0 < small["tokens"] < big["tokens"]
    assert big["max_tokens_per_run"] == 300_000


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/runs/nope").status_code == 404
    assert client.get("/runs/nope/events").status_code == 404


@pytest.mark.parametrize(
    ("approve_body", "expected_sprint"),
    [
        ({"selected": ["T1"]}, 2),  # no field: the sprint chosen at the start
        ({"selected": ["T1"], "sprint_id": 1}, 1),  # changed at approval
        ({"selected": ["T1"], "sprint_id": None}, None),  # explicitly the backlog
    ],
)
def test_sprint_choice_at_approval(
    client: TestClient, approve_body: dict[str, Any], expected_sprint: int | None
) -> None:
    res = client.post(
        "/runs",
        data={
            "inputs": json.dumps({**DEMO_INPUTS, "sprint_id": 2}),
            "transcript_text": "Anna: Add CSV export.\nMarco: Agreed.\nAnna: Thanks.",
        },
    )
    run_id = res.json()["run_id"]
    wait_for(client, run_id)
    assert client.post(f"/runs/{run_id}/approve", json=approve_body).status_code == 202
    done = wait_for(client, run_id, ("completed", "failed"))
    assert done["run"]["status"] == "completed", done["run"]["error"]
    sprint = done["sprint"]
    assert (sprint["sprint_id"] if sprint else None) == expected_sprint
    if sprint:
        assert sprint["added"] == ["DEMO-1"] and sprint["error"] is None
