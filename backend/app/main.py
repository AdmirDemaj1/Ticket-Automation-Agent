"""FastAPI app. Route handlers stay thin; logic lives in services and providers."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db import Database, DraftRow, Run, RunEvent
from app.graph.build import build_graph
from app.graph.nodes import Deps
from app.llm import LLM, build_llm
from app.models import (
    CodeFinding,
    CodeFit,
    CodeFitDecision,
    CreatedTicket,
    MeetingAnalysis,
    Requirement,
    ReviewDecision,
    ScreenshotRef,
    TicketDraft,
)
from app.providers.base import (
    CodeProvider,
    JiraIssueType,
    JiraProject,
    JiraProvider,
    ProviderError,
    ProviderNotAvailable,
    Repo,
    Sprint,
)
from app.providers.factory import get_code_provider, get_jira_provider
from app.services.intake import (
    IntakeError,
    NewRunRequest,
    UploadedFile,
    create_rerun,
    create_run,
    estimate_tokens,
)
from app.services.runs import TERMINAL, ReviewStage, RunConflict, RunManager
from app.services.tickets import run_label

log = logging.getLogger("app")

SSE_POLL_SECONDS = 0.5
SSE_HEARTBEAT_SECONDS = 15.0


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    db = Database(settings.db_path)
    db.init()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_path)) as saver:
            deps = Deps(
                settings=settings,
                db=db,
                llm=llm or build_llm(settings),
                code=lambda: get_code_provider(settings),
                jira=lambda: get_jira_provider(settings),
            )
            manager = RunManager(build_graph(deps, saver), db)
            manager.recover_interrupted()
            app.state.runs = manager
            try:
                yield
            finally:
                await manager.shutdown()

    app = FastAPI(title="Meeting to Jira (local)", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db

    origins = {settings.frontend_origin, settings.frontend_origin.replace("localhost", "127.0.0.1")}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.exception_handler(ProviderNotAvailable)
    async def _not_available(_: Request, exc: ProviderNotAvailable) -> JSONResponse:
        return JSONResponse(status_code=501, content={"detail": str(exc)})

    @app.exception_handler(ProviderError)
    async def _provider_error(_: Request, exc: ProviderError) -> JSONResponse:
        log.warning("provider error: %s", exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(IntakeError)
    async def _intake_error(_: Request, exc: IntakeError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RunConflict)
    async def _conflict(_: Request, exc: RunConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    _register_routes(app)
    return app


# ---------- dependencies ----------


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def _runs(request: Request) -> RunManager:
    runs: RunManager = request.app.state.runs
    return runs


def _code(settings: Annotated[Settings, Depends(_settings)]) -> CodeProvider:
    return get_code_provider(settings)


def _jira(settings: Annotated[Settings, Depends(_settings)]) -> JiraProvider:
    return get_jira_provider(settings)


SettingsDep = Annotated[Settings, Depends(_settings)]
DbDep = Annotated[Database, Depends(_db)]
RunsDep = Annotated[RunManager, Depends(_runs)]
CodeDep = Annotated[CodeProvider, Depends(_code)]
JiraDep = Annotated[JiraProvider, Depends(_jira)]


# ---------- response and request bodies ----------


class RunCreated(BaseModel):
    run_id: str


class Estimate(BaseModel):
    tokens: int
    max_tokens_per_run: int


class ScreenshotInfo(BaseModel):
    order: int
    caption: str | None
    url: str


class DraftView(BaseModel):
    draft: TicketDraft
    edited: bool
    jira_key: str | None
    jira_url: str | None


class SprintOutcome(BaseModel):
    sprint_id: int
    added: list[str]
    error: str | None


class RunDetail(BaseModel):
    run: Run
    transcript_title: str | None
    screenshots: list[ScreenshotInfo]
    meeting_analysis: MeetingAnalysis | None
    requirements: list[Requirement]
    code_findings: list[CodeFinding]
    files_read: list[str]
    drafts: list[DraftView]
    created: list[CreatedTicket]
    sprint: SprintOutcome | None
    tokens_used: int
    jira_labels: list[str]
    review_stage: ReviewStage | None
    code_fit: CodeFit | None


class DraftsUpdate(BaseModel):
    drafts: list[TicketDraft]


class RerunBody(BaseModel):
    repo: str
    branch: str


class ApproveBody(BaseModel):
    selected: list[str]
    sprint_id: int | None = None


# ---------- routes ----------


def _register_routes(app: FastAPI) -> None:
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/config/status")
    async def config_status(settings: SettingsDep) -> dict[str, Any]:
        """Which providers are configured. Never returns secret values."""
        return {
            "llm": {
                "provider": settings.llm_provider,
                "model": settings.anthropic_model,
                "api_key_set": settings.anthropic_api_key is not None
                and bool(settings.anthropic_api_key.get_secret_value()),
                "max_tokens_per_run": settings.max_llm_tokens_per_run,
            },
            "code": {
                "provider": settings.code_provider,
                "base_url": settings.gitlab_base_url
                if settings.code_provider == "gitlab"
                else None,
            },
            "jira": {
                "provider": settings.jira_provider,
                "base_url": settings.jira_base_url if settings.jira_provider == "jira" else None,
            },
            "limits": {
                "max_code_files": settings.max_code_files,
                "max_file_bytes": settings.max_file_bytes,
                "max_screenshots": settings.max_screenshots,
                "max_screenshot_bytes": settings.max_screenshot_bytes,
            },
        }

    @app.get("/code/repos")
    async def code_repos(code: CodeDep) -> list[Repo]:
        return await code.list_repos()

    @app.get("/code/repos/{repo_id:path}/branches")
    async def code_branches(repo_id: str, code: CodeDep) -> list[str]:
        return await code.list_branches(repo_id)

    @app.get("/jira/projects")
    async def jira_projects(jira: JiraDep) -> list[JiraProject]:
        return await jira.list_projects()

    @app.get("/jira/projects/{key}/issue-types")
    async def jira_issue_types(key: str, jira: JiraDep) -> list[JiraIssueType]:
        return await jira.list_issue_types(key)

    @app.get("/jira/projects/{key}/sprints")
    async def jira_sprints(key: str, jira: JiraDep, settings: SettingsDep) -> list[Sprint]:
        """Active and future sprints. Empty when sprint support is turned off."""
        if not settings.jira_sprints_enabled:
            return []
        return await jira.list_sprints(key)

    @app.get("/runs/estimate")
    async def run_estimate(
        settings: SettingsDep, transcript_chars: int = 0, screenshots: int = 0
    ) -> Estimate:
        return Estimate(
            tokens=estimate_tokens(max(0, transcript_chars), max(0, screenshots), settings),
            max_tokens_per_run=settings.max_llm_tokens_per_run,
        )

    @app.post("/runs", status_code=202)
    async def post_run(
        settings: SettingsDep,
        db: DbDep,
        runs: RunsDep,
        code: CodeDep,
        jira: JiraDep,
        inputs: Annotated[str, Form()],
        transcript_text: Annotated[str | None, Form()] = None,
        transcript_file: Annotated[UploadFile | None, File()] = None,
        screenshots: Annotated[list[UploadFile] | None, File()] = None,
        captions: Annotated[str, Form()] = "[]",
    ) -> RunCreated:
        shots = screenshots or []
        if len(shots) > settings.max_screenshots:
            raise IntakeError(f"At most {settings.max_screenshots} screenshots per run")
        request = NewRunRequest(
            inputs_json=inputs,
            transcript_text=transcript_text,
            transcript_file=await _read_upload(transcript_file, settings.max_transcript_bytes)
            if transcript_file is not None and transcript_file.filename
            else None,
            screenshots=[await _read_upload(s, settings.max_screenshot_bytes) for s in shots],
            captions_json=captions,
        )
        run, state = await create_run(request, settings, db, code, jira)
        runs.start(run.id, state)
        return RunCreated(run_id=run.id)

    @app.get("/runs")
    async def list_runs(db: DbDep) -> list[Run]:
        return db.list_runs()

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str, db: DbDep, runs: RunsDep) -> RunDetail:
        run = _get_run(db, run_id)
        values = await runs.state(run_id)
        transcript = values.get("transcript") or {}
        analysis = values.get("meeting_analysis")
        shots = [ScreenshotRef.model_validate(s) for s in values.get("screenshots", [])]
        return RunDetail(
            run=run,
            transcript_title=transcript.get("title"),
            screenshots=[
                ScreenshotInfo(
                    order=s.order, caption=s.caption, url=f"/runs/{run_id}/screenshots/{s.order}"
                )
                for s in shots
            ],
            meeting_analysis=MeetingAnalysis.model_validate(analysis) if analysis else None,
            requirements=[Requirement.model_validate(r) for r in values.get("requirements", [])],
            code_findings=[CodeFinding.model_validate(f) for f in values.get("code_findings", [])],
            files_read=sorted((values.get("code_files") or {}).keys()),
            drafts=[_draft_view(d) for d in db.list_drafts(run_id)],
            created=[CreatedTicket.model_validate(c) for c in values.get("created", [])],
            sprint=SprintOutcome.model_validate(values["sprint"]) if values.get("sprint") else None,
            tokens_used=int(values.get("tokens_used", 0)),
            jira_labels=[run_label(run_id), f"{run_label(run_id)}-<draft id>"],
            review_stage=await runs.stage(run_id) if run.status == "awaiting_review" else None,
            code_fit=CodeFit.model_validate(values["code_fit"]) if values.get("code_fit") else None,
        )

    @app.get("/runs/{run_id}/screenshots/{order}")
    async def get_screenshot(
        run_id: str, order: int, db: DbDep, runs: RunsDep, settings: SettingsDep
    ) -> FileResponse:
        _get_run(db, run_id)
        values = await runs.state(run_id)
        for s in values.get("screenshots", []):
            ref = ScreenshotRef.model_validate(s)
            if ref.order == order:
                path = await asyncio.to_thread(_inside, Path(ref.path), settings.runs_dir)
                if path is not None:
                    return FileResponse(path)
        raise HTTPException(status_code=404, detail="Screenshot not found")

    @app.get("/runs/{run_id}/events")
    async def run_events(
        run_id: str,
        request: Request,
        db: DbDep,
        last_event_id: Annotated[str | None, Header()] = None,
        after: int = 0,
    ) -> StreamingResponse:
        _get_run(db, run_id)
        start = _parse_event_id(last_event_id, after)
        return StreamingResponse(
            _event_stream(request, db, run_id, start),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.put("/runs/{run_id}/drafts")
    async def put_drafts(run_id: str, body: DraftsUpdate, db: DbDep) -> list[DraftView]:
        run = _get_run(db, run_id)
        if run.status != "awaiting_review":
            raise RunConflict("Drafts can only be edited while the run awaits review")
        try:
            db.save_draft_edits(run_id, body.drafts)
        except KeyError as e:
            raise HTTPException(status_code=400, detail=f"Unknown draft id(s): {e.args[0]}") from e
        return [_draft_view(d) for d in db.list_drafts(run_id)]

    @app.post("/runs/{run_id}/approve", status_code=202)
    async def approve(run_id: str, body: ApproveBody, db: DbDep, runs: RunsDep) -> Run:
        if _get_run(db, run_id).status != "awaiting_review":
            raise RunConflict("Only a run that awaits review can be approved")
        if await runs.stage(run_id) != "drafts":
            raise RunConflict("There are no drafts to approve yet")
        rows = db.list_drafts(run_id)
        known = {r.draft.temp_id for r in rows}
        selected = set(body.selected)
        if not selected:
            raise HTTPException(status_code=400, detail="Select at least one ticket to create")
        unknown = sorted(selected - known)
        if unknown:
            raise HTTPException(
                status_code=400, detail=f"Unknown draft id(s): {', '.join(unknown)}"
            )
        # The approved tickets come from the saved drafts, never from the request body.
        drafts = [
            r.draft.model_copy(update={"selected": r.draft.temp_id in selected}) for r in rows
        ]
        db.save_draft_edits(run_id, drafts)
        run = _get_run(db, run_id)
        # An explicit sprint_id (even null: "backlog") wins over the choice made at the start.
        sprint_id = body.sprint_id if "sprint_id" in body.model_fields_set else run.inputs.sprint_id
        runs.approve(run_id, ReviewDecision(decision="approve", drafts=drafts, sprint_id=sprint_id))
        return _get_run(db, run_id)

    @app.post("/runs/{run_id}/reject", status_code=202)
    async def reject(run_id: str, db: DbDep, runs: RunsDep) -> Run:
        _get_run(db, run_id)
        if await runs.stage(run_id) == "code_fit":
            runs.resolve_code_fit(run_id, CodeFitDecision(decision="stop"))
        else:
            runs.reject(run_id)
        return _get_run(db, run_id)

    @app.post("/runs/{run_id}/code-fit", status_code=202)
    async def code_fit_decision(
        run_id: str, body: CodeFitDecision, db: DbDep, runs: RunsDep
    ) -> Run:
        _get_run(db, run_id)
        if await runs.stage(run_id) != "code_fit":
            raise RunConflict("The run is not waiting for a code-fit decision")
        runs.resolve_code_fit(run_id, body)
        return _get_run(db, run_id)

    @app.post("/runs/{run_id}/rerun", status_code=202)
    async def rerun(
        run_id: str,
        body: RerunBody,
        settings: SettingsDep,
        db: DbDep,
        runs: RunsDep,
        code: CodeDep,
    ) -> RunCreated:
        """Run the code steps again on another repository, reusing the meeting work."""
        source = _get_run(db, run_id)
        values = await runs.state(run_id)
        new_run, state = await create_rerun(
            source, values, body.repo, body.branch, settings, db, code
        )
        runs.start(new_run.id, state)
        db.add_event(
            run_id, "run", "info", f"Re-run on {body.repo} @ {body.branch} as run {new_run.id[:8]}"
        )
        if await runs.stage(run_id) == "code_fit":
            runs.resolve_code_fit(run_id, CodeFitDecision(decision="stop"))
        return RunCreated(run_id=new_run.id)

    @app.post("/runs/{run_id}/cancel")
    async def cancel(run_id: str, db: DbDep, runs: RunsDep) -> Run:
        _get_run(db, run_id)
        await runs.cancel(run_id)
        return _get_run(db, run_id)

    @app.post("/runs/{run_id}/retry", status_code=202)
    async def retry(run_id: str, db: DbDep, runs: RunsDep) -> Run:
        _get_run(db, run_id)
        runs.retry(run_id)
        return _get_run(db, run_id)


# ---------- helpers ----------


def _get_run(db: Database, run_id: str) -> Run:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _inside(path: Path, root: Path) -> Path | None:
    """The resolved path if it is an existing file under `root`, else None."""
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(root.resolve()) and resolved.is_file() else None


def _draft_view(row: DraftRow) -> DraftView:
    return DraftView(
        draft=row.draft, edited=row.edited, jira_key=row.jira_key, jira_url=row.jira_url
    )


async def _read_upload(upload: UploadFile, max_bytes: int) -> UploadedFile:
    # Read one byte past the limit so oversized files are rejected without reading them whole.
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise IntakeError(f"{upload.filename or 'upload'}: larger than {max_bytes // 1_000_000} MB")
    return UploadedFile(filename=upload.filename or "", data=data)


def _parse_event_id(header: str | None, after: int) -> int:
    if header:
        try:
            return max(0, int(header))
        except ValueError:
            return 0
    return max(0, after)


def _sse(event: RunEvent) -> str:
    return f"id: {event.id}\nevent: progress\ndata: {event.model_dump_json()}\n\n"


async def _event_stream(
    request: Request, db: Database, run_id: str, start: int
) -> AsyncIterator[str]:
    last = start
    idle = 0.0
    yield "retry: 2000\n\n"
    while True:
        if await request.is_disconnected():
            return
        events = db.list_events(run_id, last)
        for event in events:
            yield _sse(event)
            last = event.id
        run = db.get_run(run_id)
        if run is None or (run.status in TERMINAL and not events):
            status = run.status if run else "deleted"
            yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
            return
        if events:
            idle = 0.0
        else:
            idle += SSE_POLL_SECONDS
            if idle >= SSE_HEARTBEAT_SECONDS:
                idle = 0.0
                yield ": ping\n\n"
        await asyncio.sleep(SSE_POLL_SECONDS)
