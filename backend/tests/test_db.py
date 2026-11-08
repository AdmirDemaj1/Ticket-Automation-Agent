from pathlib import Path

import pytest

from app.db import Database
from app.models import RunInputs

INPUTS = RunInputs(repo="fixtures/demo-app", branch="main", jira_project_key="DEMO")


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "app.db")
    database.init()
    return database


def test_create_and_get_run(db: Database) -> None:
    run = db.create_run(INPUTS)
    assert run.status == "queued"
    assert db.get_run(run.id) == run
    assert db.get_run("missing") is None


def test_list_runs_newest_first(db: Database) -> None:
    first = db.create_run(INPUTS)
    second = db.create_run(INPUTS)
    assert [r.id for r in db.list_runs()] == [second.id, first.id]


def test_set_status(db: Database) -> None:
    run = db.create_run(INPUTS)
    db.set_status(run.id, "failed", error="boom")
    updated = db.get_run(run.id)
    assert updated is not None
    assert (updated.status, updated.error) == ("failed", "boom")
    with pytest.raises(ValueError):
        db.set_status(run.id, "exploded")  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        db.set_status("missing", "running")


def test_events_in_order_and_after_id(db: Database) -> None:
    run = db.create_run(INPUTS)
    a = db.add_event(run.id, "load_transcript", "info", "started")
    b = db.add_event(run.id, "load_transcript", "info", "done")
    assert [e.id for e in db.list_events(run.id)] == [a.id, b.id]
    assert [e.id for e in db.list_events(run.id, after_id=a.id)] == [b.id]


def test_init_is_idempotent_and_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "app.db"
    Database(path).init()
    run = Database(path).create_run(INPUTS)
    reopened = Database(path)
    reopened.init()
    assert reopened.get_run(run.id) is not None
