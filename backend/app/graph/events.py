"""Progress events, stored in SQLite and streamed to the browser over SSE."""

import functools
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from app.db import Database
from app.graph.state import RunState

log = logging.getLogger("app.graph")


class NodeFn(Protocol):
    # Named `state` to match LangGraph's node protocol.
    def __call__(self, state: RunState) -> Coroutine[Any, Any, dict[str, Any]]: ...


class Events:
    def __init__(self, db: Database) -> None:
        self.db = db

    def info(self, run_id: str, step: str, message: str) -> None:
        self.db.add_event(run_id, step, "info", message)

    def warning(self, run_id: str, step: str, message: str) -> None:
        self.db.add_event(run_id, step, "warning", message)

    def error(self, run_id: str, step: str, message: str) -> None:
        self.db.add_event(run_id, step, "error", message)


def tracked(events: Events, step: str, label: str) -> Callable[[NodeFn], NodeFn]:
    """Emit an event when a node starts and when it ends.

    Not for `human_review`: anything before `interrupt()` runs again on resume.
    Errors are re-raised unchanged so the run manager can mark the run failed.
    """

    def wrap(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def inner(state: RunState) -> dict[str, Any]:
            run_id = state["run_id"]
            events.info(run_id, step, f"{label}…")
            started = time.monotonic()
            update = await fn(state)
            seconds = time.monotonic() - started
            summary = update.pop("_summary", None)
            done = f"{label}: done in {seconds:.1f}s"
            events.info(run_id, step, f"{done}. {summary}" if summary else done)
            return update

        return inner

    return wrap
