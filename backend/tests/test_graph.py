"""The whole graph on fixtures: interrupt -> (new checkpointer = restart) -> resume -> create."""

import shutil

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.config import Settings
from app.db import Database
from app.graph.build import build_graph, thread_config
from app.graph.nodes import Deps
from app.graph.state import RunState
from app.llm import FakeLLM
from app.models import ReviewDecision, RunInputs
from app.providers.factory import get_code_provider
from app.providers.fakes import FakeJiraProvider
from tests.conftest import DEMO_INPUTS, FIXTURES


def _deps(settings: Settings, db: Database, jira: FakeJiraProvider) -> Deps:
    return Deps(
        settings=settings,
        db=db,
        llm=FakeLLM(FIXTURES / "llm"),
        code=lambda: get_code_provider(settings),
        jira=lambda: jira,
    )


def _initial(settings: Settings, db: Database) -> RunState:
    run = db.create_run(RunInputs.model_validate(DEMO_INPUTS))
    folder = settings.runs_dir / run.id
    folder.mkdir(parents=True)
    shutil.copy(FIXTURES / "transcript.vtt", folder / "transcript.vtt")
    shots = []
    for order, name in enumerate(("01-login.png", "02-dashboard.png"), start=1):
        shutil.copy(FIXTURES / "screenshots" / name, folder / name)
        shots.append({"path": str(folder / name), "order": order, "caption": None})
    return {
        "run_id": run.id,
        "inputs": DEMO_INPUTS,
        "transcript_path": str(folder / "transcript.vtt"),
        "screenshots": shots,
        "tokens_used": 0,
        "errors": [],
    }


async def test_interrupt_restart_resume_create(settings: Settings) -> None:
    db = Database(settings.db_path)
    db.init()
    jira = FakeJiraProvider(settings.data_dir / "fake_jira.json")
    initial = _initial(settings, db)
    run_id = initial["run_id"]
    config = thread_config(run_id)
    checkpoints = str(settings.checkpoint_path)

    async with AsyncSqliteSaver.from_conn_string(checkpoints) as saver:
        graph = build_graph(_deps(settings, db, jira), saver)
        result = await graph.ainvoke(initial, config)
        assert "__interrupt__" in result
        snapshot = await graph.aget_state(config)
        assert snapshot.next == ("human_review",)
    assert jira.calls == []  # nothing written before review

    drafts = [row.draft for row in db.list_drafts(run_id)]
    assert len(drafts) == 6
    assert all(d.requirement_ids for d in drafts)
    values = snapshot.values
    with_evidence = [f for f in values["code_findings"] if f["evidence"]]
    assert len(with_evidence) == 6
    assert {f["requirement_id"]: f["status"] for f in values["code_findings"]} == {
        "R1": "missing",
        "R2": "implemented",
        "R3": "partial",
        "R4": "partial",
        "R5": "missing",
        "R6": "missing",
    }

    # Simulated restart: a brand new checkpointer and graph on the same files.
    async with AsyncSqliteSaver.from_conn_string(checkpoints) as saver:
        graph = build_graph(_deps(settings, db, jira), saver)
        decision = ReviewDecision(decision="approve", drafts=drafts)
        await graph.ainvoke(Command(resume=decision.model_dump()), config)
        final = (await graph.aget_state(config)).values

    assert final["review"]["decision"] == "approve"
    created = final["created"]
    assert len(created) == 5  # T6 (already done, high confidence) was not selected
    assert all(c["key"] for c in created)
    stored = jira.stored_issues()
    assert len(stored) == 5
    assert all(f"mtj-{run_id}" in issue["labels"] for issue in stored)
    keys = {row.draft.temp_id: row.jira_key for row in db.list_drafts(run_id)}
    assert keys["T1"] == "DEMO-1" and keys["T6"] is None


async def test_reject_creates_nothing(settings: Settings) -> None:
    db = Database(settings.db_path)
    db.init()
    jira = FakeJiraProvider(settings.data_dir / "fake_jira.json")
    initial = _initial(settings, db)
    config = thread_config(initial["run_id"])
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as saver:
        graph = build_graph(_deps(settings, db, jira), saver)
        await graph.ainvoke(initial, config)
        await graph.ainvoke(Command(resume={"decision": "reject", "drafts": []}), config)
        final = (await graph.aget_state(config)).values
    assert final["review"]["decision"] == "reject"
    assert "created" not in final
    assert [name for name, _ in jira.calls] == []
    assert jira.stored_issues() == []
