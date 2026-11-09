"""Runs the graph in background tasks and keeps the run status in SQLite in step with it.

- start:  input state  -> runs until the review interrupt -> `awaiting_review`
- resume: Command(resume=decision) on the same thread -> `completed` or `cancelled`
- retry:  None on the same thread -> continues from the last checkpoint after a failure

Because checkpoints live in SQLite, a run paused for review survives a backend restart.
Runs that were mid-step when the backend stopped are marked `failed` on startup and can be
retried from their last checkpoint.
"""

import asyncio
import logging
from typing import Any, Literal

from langgraph.types import Command

from app.db import Database
from app.graph.build import Graph, thread_config
from app.graph.nodes import ApprovalRequired
from app.graph.state import RunState
from app.llm import LLMError
from app.models import CodeFitDecision, ReviewDecision, RunStatus
from app.providers.base import ProviderError
from app.providers.transcript import TranscriptError

log = logging.getLogger("app.runs")

ReviewStage = Literal["code_fit", "drafts"]
ACTIVE: tuple[RunStatus, ...] = ("queued", "running", "creating_tickets")
TERMINAL: tuple[RunStatus, ...] = ("completed", "failed", "cancelled")
_SAFE_ERRORS = (LLMError, ProviderError, TranscriptError, ApprovalRequired)


class RunConflict(Exception):
    """The run is not in a state that allows this action. Message is safe to show."""


class RunManager:
    def __init__(self, graph: Graph, db: Database) -> None:
        self.graph = graph
        self.db = db
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._user_cancelled: set[str] = set()

    # ---------- lifecycle ----------

    def recover_interrupted(self) -> None:
        for run in self.db.list_runs(limit=10_000):
            if run.status in ACTIVE:
                msg = "The backend stopped while this run was in progress. Retry to continue."
                self.db.set_status(run.id, "failed", msg)
                self.db.add_event(run.id, "run", "error", msg)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def wait(self, run_id: str) -> None:
        """Wait for the run's current background task (tests and graceful shutdown)."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    # ---------- actions ----------

    def start(self, run_id: str, initial: RunState) -> None:
        self.db.add_event(run_id, "run", "info", "Run started")
        self._spawn(run_id, initial, "running")

    def approve(self, run_id: str, decision: ReviewDecision) -> None:
        self._require(run_id, "awaiting_review")
        count = sum(1 for d in decision.drafts if d.selected)
        self.db.add_event(run_id, "review", "info", f"Approved {count} ticket(s)")
        self._spawn(run_id, Command(resume=decision.model_dump()), "creating_tickets")

    def reject(self, run_id: str) -> None:
        self._require(run_id, "awaiting_review")
        self.db.add_event(run_id, "review", "info", "Rejected; no tickets will be created")
        decision = ReviewDecision(decision="reject")
        self._spawn(run_id, Command(resume=decision.model_dump()), "running")

    def resolve_code_fit(self, run_id: str, decision: CodeFitDecision) -> None:
        self._require(run_id, "awaiting_review")
        if decision.decision == "draft_anyway":
            self.db.add_event(run_id, "review", "info", "Drafting tickets anyway, as requested")
        else:
            self.db.add_event(run_id, "review", "info", "Stopped; no tickets will be drafted")
        self._spawn(run_id, Command(resume=decision.model_dump()), "running")

    def retry(self, run_id: str) -> None:
        self._require(run_id, "failed")
        self.db.add_event(run_id, "run", "info", "Retrying from the last checkpoint")
        self._spawn(run_id, None, "running")

    async def cancel(self, run_id: str) -> None:
        run = self.db.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status in TERMINAL:
            raise RunConflict(f"The run is already {run.status}")
        if run.status == "creating_tickets":
            raise RunConflict("Tickets are being created; the run can no longer be cancelled")
        self._user_cancelled.add(run_id)
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.db.set_status(run_id, "cancelled")
        self.db.add_event(run_id, "run", "warning", "Run cancelled")

    async def stage(self, run_id: str) -> ReviewStage | None:
        """Which pause the run is in: the code-fit check or the draft review."""
        snapshot = await self.graph.aget_state(thread_config(run_id))
        if "code_fit_review" in snapshot.next:
            return "code_fit"
        if "human_review" in snapshot.next:
            return "drafts"
        return None

    async def state(self, run_id: str) -> dict[str, Any]:
        snapshot = await self.graph.aget_state(thread_config(run_id))
        return dict(snapshot.values or {})

    # ---------- internals ----------

    def _require(self, run_id: str, status: RunStatus) -> None:
        run = self.db.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status != status:
            raise RunConflict(f"The run is {run.status.replace('_', ' ')}, not {status}")
        if run_id in self._tasks:
            raise RunConflict("The run is busy")

    def _spawn(self, run_id: str, payload: Any, status: RunStatus) -> None:
        # Set the status before returning so a second click sees the new state.
        self.db.set_status(run_id, status)
        task = asyncio.create_task(self._drive(run_id, payload), name=f"run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))

    async def _drive(self, run_id: str, payload: Any) -> None:
        config = thread_config(run_id)
        try:
            await self.graph.ainvoke(payload, config)
        except asyncio.CancelledError:
            if run_id not in self._user_cancelled:
                log.info("run %s interrupted by shutdown", run_id)
            raise
        except Exception as e:
            message = str(e) if isinstance(e, _SAFE_ERRORS) else _internal(e)
            if not isinstance(e, _SAFE_ERRORS):
                log.exception("run %s failed", run_id)
            self.db.set_status(run_id, "failed", message)
            self.db.add_event(run_id, "run", "error", f"Run failed: {message}")
            return

        snapshot = await self.graph.aget_state(config)
        if "code_fit_review" in snapshot.next:
            fit = (snapshot.values or {}).get("code_fit") or {}
            self.db.set_status(run_id, "awaiting_review")
            self.db.add_event(
                run_id,
                "review",
                "warning",
                "No tickets drafted: the code does not seem to match the meeting. "
                + (fit.get("reason") or "")
                + " Choose another repository, or draft anyway.",
            )
            return
        if "human_review" in snapshot.next:
            self.db.set_status(run_id, "awaiting_review")
            self.db.add_event(run_id, "review", "info", "Drafts are ready for review")
            return
        values = snapshot.values or {}
        review = values.get("review") or {}
        if review.get("decision") == "approve":
            created = values.get("created") or []
            failed = [c for c in created if c.get("error")]
            self.db.set_status(run_id, "completed")
            level = "warning" if failed else "info"
            note = f" ({len(failed)} failed)" if failed else ""
            self.db.add_event(run_id, "run", level, f"Run completed{note}")
        else:
            self.db.set_status(run_id, "cancelled")
            self.db.add_event(run_id, "run", "info", "Run finished without creating tickets")


def _internal(e: Exception) -> str:
    # Exception text may contain transcript or code; keep it in the server log only.
    return f"Internal error ({type(e).__name__}). See the backend log for details."
