"""Node-level tests with the fake LLM and fake providers."""

from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.db import Database
from app.graph.nodes import (
    ApprovalRequired,
    Deps,
    Nodes,
    check_findings,
    finalize_drafts,
    rank_paths,
)
from app.graph.state import RunState
from app.llm import FakeLLM, Image, Text
from app.models import (
    CodeFinding,
    DraftList,
    Evidence,
    Requirement,
    ReviewDecision,
    RunInputs,
    TicketDraftOut,
)
from app.providers.base import FileEntry
from app.providers.factory import get_code_provider
from app.providers.fakes import FakeJiraProvider
from tests.conftest import DEMO_INPUTS, FIXTURES


def _deps(settings: Settings, llm: FakeLLM, jira: FakeJiraProvider | None = None) -> Deps:
    db = Database(settings.db_path)
    db.init()
    jira = jira or FakeJiraProvider(settings.data_dir / "fake_jira.json")
    return Deps(
        settings=settings,
        db=db,
        llm=llm,
        code=lambda: get_code_provider(settings),
        jira=lambda: jira,
    )


def _req(rid: str, title: str = "t", detail: str = "d") -> Requirement:
    return Requirement(id=rid, title=title, detail=detail)


def _state(db: Database, **extra: Any) -> RunState:
    run = db.create_run(RunInputs.model_validate(DEMO_INPUTS))
    state: RunState = {"run_id": run.id, "inputs": DEMO_INPUTS, "tokens_used": 0}
    state.update(extra)  # type: ignore[typeddict-item]
    return state


async def test_analyze_sends_screenshots_in_order_with_captions(
    settings: Settings, tmp_path: Path
) -> None:
    llm = FakeLLM(FIXTURES / "llm")
    deps = _deps(settings, llm)
    shots = []
    for order, name in ((2, "02-dashboard.png"), (1, "01-login.png")):
        target = tmp_path / name
        target.write_bytes((FIXTURES / "screenshots" / name).read_bytes())
        shots.append({"path": str(target), "order": order, "caption": name[3:-4].title()})
    transcript = {"title": "T", "segments": [{"speaker": "A", "start_s": 1.0, "text": "hi"}]}
    state = _state(deps.db, transcript=transcript, screenshots=shots)

    update = await Nodes(deps).analyze_meeting(state)

    assert update["tokens_used"] > 0
    content = llm.calls[0].content
    kinds = [type(p).__name__ for p in content]
    assert kinds == ["Text", "Text", "Image", "Text", "Image", "Text"]
    assert isinstance(content[1], Text) and 'number="1" caption="Login"' in content[1].text
    assert isinstance(content[3], Text) and 'caption="Dashboard"' in content[3].text
    assert isinstance(content[2], Image) and content[2].media_type == "image/png"
    assert "untrusted data" in llm.calls[0].system


async def test_plan_ignores_paths_not_in_the_repository(settings: Settings) -> None:
    llm = FakeLLM(
        FIXTURES / "llm",
        overrides={"plan_code_reading": {"paths": ["src/secret/hack.ts", "/src/pages/Login.tsx"]}},
    )
    deps = _deps(settings, llm)
    state = _state(deps.db, requirements=[_req("R1", "login").model_dump()])
    update = await Nodes(deps).plan_code_reading(state)
    assert update["code_candidates"] == ["src/pages/Login.tsx"]
    assert "ignored 1 path" in update["_summary"]


async def test_read_code_respects_the_total_byte_budget(settings: Settings) -> None:
    tight = settings.model_copy(update={"max_total_code_bytes": 1_200})
    deps = _deps(tight, FakeLLM(FIXTURES / "llm"))
    state = _state(
        deps.db,
        code_candidates=["src/pages/Login.tsx", "src/api/auth.ts", "src/pages/Dashboard.tsx"],
    )
    update = await Nodes(deps).read_code(state)
    files = update["code_files"]
    assert sum(len(t.encode()) for t in files.values()) <= 1_200
    assert "src/api/auth.ts" in files and "src/pages/Login.tsx" not in files
    assert "skipped 2" in update["_summary"]


def test_check_findings_drops_invented_evidence_and_fills_gaps() -> None:
    files = {"a.ts": "line1\nline2\nline3"}
    reqs = [_req("R1"), _req("R2"), _req("R3")]
    findings = [
        CodeFinding(
            requirement_id="R1",
            status="implemented",
            evidence=[Evidence(path="ghost.ts", start_line=1, end_line=2, note="x")],
            affected_files=["ghost.ts"],
            confidence="high",
        ),
        CodeFinding(
            requirement_id="R2",
            status="partial",
            evidence=[
                Evidence(path="a.ts", start_line=2, end_line=3, note="ok"),
                Evidence(path="a.ts", start_line=2, end_line=99, note="past the end"),
            ],
            affected_files=["a.ts"],
            confidence="high",
        ),
    ]
    out = {f.requirement_id: f for f in check_findings(findings, reqs, files)}
    assert (out["R1"].status, out["R1"].confidence, out["R1"].evidence) == ("unclear", "low", [])
    assert out["R1"].affected_files == []
    assert [e.end_line for e in out["R2"].evidence] == [3]
    assert out["R2"].confidence == "medium"
    assert (out["R3"].status, out["R3"].confidence) == ("unclear", "low")


def _out(**kw: Any) -> TicketDraftOut:
    base: dict[str, Any] = {
        "type": "Story",
        "title": "Do the thing",
        "description": "d",
        "acceptance_criteria": ["a", " "],
        "estimate": None,
        "labels": ["Login", "login "],
        "related_files": ["a.ts", "invented.ts"],
        "requirement_ids": ["R1"],
        "status_in_code": "new",
    }
    base.update(kw)
    return TicketDraftOut.model_validate(base)


def test_finalize_drafts_ids_types_dedupe_and_selection() -> None:
    reqs = [_req("R1"), _req("R2"), _req("R3")]
    findings = [
        CodeFinding(
            requirement_id="R2",
            status="implemented",
            evidence=[],
            affected_files=[],
            confidence="high",
        ),
        CodeFinding(
            requirement_id="R3",
            status="implemented",
            evidence=[],
            affected_files=[],
            confidence="medium",
        ),
    ]
    drafted = DraftList(
        drafts=[
            _out(type="Bug"),
            _out(title="do  the THING", requirement_ids=["R9", "R3"]),
            _out(title="Already there", requirement_ids=["R2"], status_in_code="already_done"),
            _out(title="Maybe there", requirement_ids=["R3"], status_in_code="already_done"),
        ]
    )
    drafts = finalize_drafts(drafted, reqs, findings, ["Story", "Task"], {"a.ts": ""})
    assert [d.temp_id for d in drafts] == ["T1", "T2", "T3"]
    first = drafts[0]
    assert first.type == "Story"  # Bug not allowed
    assert first.requirement_ids == ["R1", "R3"]  # merged duplicate, unknown R9 dropped
    assert first.labels == ["login"]
    assert first.related_files == ["a.ts"]
    assert first.acceptance_criteria == ["a"]
    assert [d.selected for d in drafts] == [True, False, True]


def test_rank_paths_prefers_matching_source_files() -> None:
    tree = [
        FileEntry(path="README.md"),
        FileEntry(path="src/pages/Dashboard.tsx"),
        FileEntry(path="docs/dashboard.md"),
        FileEntry(path="src/api/orders.ts"),
    ]
    ranked = rank_paths(tree, [_req("R1", "Dashboard filter", "orders by date")])
    assert {e.path for e in ranked[:2]} == {"src/pages/Dashboard.tsx", "src/api/orders.ts"}
    assert ranked[2].path == "docs/dashboard.md"  # matches, but not a source file


async def test_create_tickets_refuses_without_approval(settings: Settings) -> None:
    jira = FakeJiraProvider(settings.data_dir / "fake_jira.json")
    deps = _deps(settings, FakeLLM(FIXTURES / "llm"), jira)
    nodes = Nodes(deps)
    with pytest.raises(ApprovalRequired):
        await nodes.create_tickets(_state(deps.db))
    rejected = ReviewDecision(decision="reject").model_dump()
    with pytest.raises(ApprovalRequired):
        await nodes.create_tickets(_state(deps.db, review=rejected))
    assert [name for name, _ in jira.calls] == []
