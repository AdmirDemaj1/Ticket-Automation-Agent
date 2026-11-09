"""The code-fit gate: no drafts when the repository does not match the meeting."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.graph.nodes import assess_code_fit
from app.llm import FakeLLM
from app.main import create_app
from app.models import CodeFinding, RepositoryFit
from tests.conftest import FIXTURES, start_fixture_run, wait_for


def _finding(rid: str, status: str = "unclear", confidence: str = "low") -> CodeFinding:
    return CodeFinding.model_validate(
        {
            "requirement_id": rid,
            "status": status,
            "evidence": [],
            "affected_files": [],
            "confidence": confidence,
        }
    )


def _fit(verdict: str, reason: str = "r") -> RepositoryFit:
    return RepositoryFit.model_validate({"verdict": verdict, "reason": reason})


@pytest.mark.parametrize(
    ("findings", "verdict", "files", "ok"),
    [
        ([_finding("R1", "missing", "high")], "matches", 3, True),
        ([_finding("R1", "missing", "high")], "does_not_match", 3, False),
        ([_finding("R1")] * 4, "cannot_tell", 3, False),  # nothing checked confidently
        ([_finding("R1")] * 4, "matches", 3, True),  # model is sure: trust it
        ([_finding("R1", "partial", "medium")] + [_finding("R2")] * 3, "partly", 3, True),  # 25%
        ([_finding("R1", "partial", "medium")] + [_finding("R2")] * 4, "partly", 3, False),  # 20%
        ([_finding("R1", "missing", "high")], "matches", 0, False),  # no code read at all
    ],
)
def test_assess_code_fit(findings: list[CodeFinding], verdict: str, files: int, ok: bool) -> None:
    assert assess_code_fit(findings, _fit(verdict), files).ok is ok


def test_assess_code_fit_counts_and_reasons() -> None:
    fit = assess_code_fit([_finding("R1", "missing", "high"), _finding("R2")], _fit("partly"), 2)
    assert (fit.confident, fit.total, fit.files_read) == (1, 2, 2)
    empty = assess_code_fit([_finding("R1")], _fit("cannot_tell", ""), 0)
    assert "No code files" in empty.reason


MISMATCH: dict[str, Any] = {
    "findings": [
        {
            "requirement_id": f"R{i}",
            "status": "unclear",
            "evidence": [],
            "affected_files": [],
            "confidence": "low",
        }
        for i in range(1, 7)
    ],
    "repository_fit": {
        "verdict": "does_not_match",
        "reason": "The meeting is about a mobile onboarding flow; this is a web admin app.",
    },
}


def _mismatch_app(settings: Settings) -> tuple[TestClient, FakeLLM]:
    llm = FakeLLM(FIXTURES / "llm", overrides={"compare_with_code": MISMATCH})
    return TestClient(create_app(settings, llm=llm)), llm


def test_mismatch_pauses_without_drafts(settings: Settings) -> None:
    client, llm = _mismatch_app(settings)
    with client:
        run_id = start_fixture_run(client)
        detail = wait_for(client, run_id)
        assert detail["run"]["status"] == "awaiting_review"
        assert detail["review_stage"] == "code_fit"
        assert detail["code_fit"]["ok"] is False
        assert "mobile onboarding" in detail["code_fit"]["reason"]
        assert detail["drafts"] == []
        assert "draft_tickets" not in [c.step for c in llm.calls]
        res = client.post(f"/runs/{run_id}/approve", json={"selected": ["T1"]})
        assert res.status_code == 409

        events = client.app.state.db.list_events(run_id)  # type: ignore[attr-defined]
        assert any("does not seem to match" in e.message for e in events)


def test_draft_anyway_continues_to_review(settings: Settings) -> None:
    client, _ = _mismatch_app(settings)
    with client:
        run_id = start_fixture_run(client)
        wait_for(client, run_id)
        res = client.post(f"/runs/{run_id}/code-fit", json={"decision": "draft_anyway"})
        assert res.status_code == 202
        detail = wait_for(client, run_id)
        assert detail["review_stage"] == "drafts"
        assert len(detail["drafts"]) == 6


def test_stop_cancels_without_tickets(settings: Settings) -> None:
    client, _ = _mismatch_app(settings)
    with client:
        run_id = start_fixture_run(client)
        wait_for(client, run_id)
        assert client.post(f"/runs/{run_id}/reject").status_code == 202
        detail = wait_for(client, run_id, ("cancelled",))
        assert detail["drafts"] == [] and detail["created"] == []
    assert not (settings.data_dir / "fake_jira.json").exists()


def test_rerun_reuses_meeting_work_and_closes_the_old_run(settings: Settings) -> None:
    client, llm = _mismatch_app(settings)
    with client:
        old_id = start_fixture_run(client)
        wait_for(client, old_id)
        del llm.overrides["compare_with_code"]  # the "right" repository matches
        calls_before = len(llm.calls)

        res = client.post(
            f"/runs/{old_id}/rerun", json={"repo": "fixtures/demo-app", "branch": "main"}
        )
        assert res.status_code == 202, res.text
        new_id = res.json()["run_id"]
        new = wait_for(client, new_id)

        assert new["review_stage"] == "drafts" and len(new["drafts"]) == 6
        assert [c.step for c in llm.calls[calls_before:]] == [
            "plan_code_reading",
            "compare_with_code",
            "draft_tickets",
        ]
        assert len(new["requirements"]) == 6
        assert [s["caption"] for s in new["screenshots"]] == ["Login", "Dashboard"]
        assert client.get(new["screenshots"][0]["url"]).status_code == 200
        assert wait_for(client, old_id, ("cancelled",))["run"]["status"] == "cancelled"

        bad = client.post(
            f"/runs/{old_id}/rerun", json={"repo": "fixtures/demo-app", "branch": "x"}
        )
        assert bad.status_code == 400 and "Branch 'x' not found" in bad.json()["detail"]


def test_code_fit_decision_needs_the_code_fit_pause(client: TestClient) -> None:
    run_id = start_fixture_run(client)
    assert wait_for(client, run_id)["review_stage"] == "drafts"
    res = client.post(f"/runs/{run_id}/code-fit", json={"decision": "draft_anyway"})
    assert res.status_code == 409
