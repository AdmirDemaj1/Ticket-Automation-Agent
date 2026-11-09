"""SQLite storage for runs, events and drafts.

One short-lived connection per operation keeps this safe to use from request handlers and
background graph threads alike. Run data only; no credentials are ever stored here.
"""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.models import RUN_STATUSES, RunInputs, RunStatus, TicketDraft

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    input_json  TEXT NOT NULL,
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    ts       TEXT NOT NULL,
    step     TEXT NOT NULL,
    level    TEXT NOT NULL,
    message  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, id);
CREATE TABLE IF NOT EXISTS drafts (
    run_id    TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    temp_id   TEXT NOT NULL,
    json      TEXT NOT NULL,
    selected  INTEGER NOT NULL DEFAULT 1,
    edited    INTEGER NOT NULL DEFAULT 0,
    jira_key  TEXT,
    jira_url  TEXT,
    PRIMARY KEY (run_id, temp_id)
);
"""

EventLevel = str  # "info" | "warning" | "error"


class Run(BaseModel):
    id: str
    status: RunStatus
    inputs: RunInputs
    error: str | None
    created_at: str
    updated_at: str


class RunEvent(BaseModel):
    id: int
    run_id: str
    ts: str
    step: str
    level: EventLevel
    message: str


class DraftRow(BaseModel):
    draft: TicketDraft
    edited: bool
    jira_key: str | None
    jira_url: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:  # commits on success, rolls back on error
                yield conn
        finally:
            conn.close()

    # --- runs ---

    def create_run(self, inputs: RunInputs) -> Run:
        run_id = uuid.uuid4().hex
        now = _now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, status, input_json, created_at, updated_at)"
                " VALUES (?, 'queued', ?, ?, ?)",
                (run_id, inputs.model_dump_json(), now, now),
            )
        run = self.get_run(run_id)
        if run is None:
            raise RuntimeError("run vanished right after insert")
        return run

    def get_run(self, run_id: str) -> Run | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row else None

    def list_runs(self, limit: int = 100) -> list[Run]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_run(r) for r in rows]

    def set_status(self, run_id: str, status: RunStatus, error: str | None = None) -> None:
        if status not in RUN_STATUSES:
            raise ValueError(f"unknown run status {status!r}")
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, _now(), run_id),
            )
            if cur.rowcount == 0:
                raise KeyError(run_id)

    # --- events ---

    def add_event(self, run_id: str, step: str, level: EventLevel, message: str) -> RunEvent:
        ts = _now()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO run_events (run_id, ts, step, level, message) VALUES (?, ?, ?, ?, ?)",
                (run_id, ts, step, level, message),
            )
            event_id = cur.lastrowid
        if event_id is None:
            raise RuntimeError("sqlite did not return an event id")
        return RunEvent(id=event_id, run_id=run_id, ts=ts, step=step, level=level, message=message)

    def list_events(self, run_id: str, after_id: int = 0) -> list[RunEvent]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM run_events WHERE run_id = ? AND id > ? ORDER BY id",
                (run_id, after_id),
            ).fetchall()
        return [RunEvent(**dict(r)) for r in rows]

    # --- drafts ---

    def replace_drafts(self, run_id: str, drafts: list[TicketDraft]) -> None:
        """Store freshly generated drafts, dropping any earlier ones for the run."""
        with self.connect() as conn:
            conn.execute("DELETE FROM drafts WHERE run_id = ?", (run_id,))
            conn.executemany(
                "INSERT INTO drafts (run_id, temp_id, json, selected, edited)"
                " VALUES (?, ?, ?, ?, 0)",
                [(run_id, d.temp_id, d.model_dump_json(), int(d.selected)) for d in drafts],
            )

    def list_drafts(self, run_id: str) -> list[DraftRow]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM drafts WHERE run_id = ? ORDER BY rowid", (run_id,)
            ).fetchall()
        return [_row_to_draft(r) for r in rows]

    def save_draft_edits(self, run_id: str, drafts: list[TicketDraft]) -> None:
        """Overwrite drafts the user edited. Every temp_id must already exist for the run."""
        with self.connect() as conn:
            current = {
                r["temp_id"]: r["json"]
                for r in conn.execute(
                    "SELECT temp_id, json FROM drafts WHERE run_id = ?", (run_id,)
                )
            }
            unknown = [d.temp_id for d in drafts if d.temp_id not in current]
            if unknown:
                raise KeyError(", ".join(unknown))
            for d in drafts:
                new_json = d.model_dump_json()
                conn.execute(
                    "UPDATE drafts SET json = ?, selected = ?,"
                    " edited = MAX(edited, ?) WHERE run_id = ? AND temp_id = ?",
                    (
                        new_json,
                        int(d.selected),
                        int(_content_changed(current[d.temp_id], d)),
                        run_id,
                        d.temp_id,
                    ),
                )

    def set_draft_jira(self, run_id: str, temp_id: str, key: str, url: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE drafts SET jira_key = ?, jira_url = ? WHERE run_id = ? AND temp_id = ?",
                (key, url, run_id, temp_id),
            )


def _content_changed(old_json: str, new: TicketDraft) -> bool:
    old = TicketDraft.model_validate_json(old_json).model_dump(exclude={"selected"})
    return old != new.model_dump(exclude={"selected"})


def _row_to_draft(row: sqlite3.Row) -> DraftRow:
    draft = TicketDraft.model_validate_json(row["json"])
    draft = draft.model_copy(update={"selected": bool(row["selected"])})
    return DraftRow(
        draft=draft, edited=bool(row["edited"]), jira_key=row["jira_key"], jira_url=row["jira_url"]
    )


def _row_to_run(row: sqlite3.Row) -> Run:
    data: dict[str, Any] = dict(row)
    return Run(
        id=data["id"],
        status=data["status"],
        inputs=RunInputs.model_validate(json.loads(data["input_json"])),
        error=data["error"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
    )
