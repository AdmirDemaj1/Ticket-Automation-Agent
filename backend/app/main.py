"""FastAPI app. Route handlers stay thin; logic lives in services and providers."""

import logging
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.db import Database, Run
from app.providers.base import (
    CodeProvider,
    JiraIssueType,
    JiraProject,
    JiraProvider,
    ProviderError,
    ProviderNotAvailable,
    Repo,
)
from app.providers.factory import get_code_provider, get_jira_provider

log = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    db = Database(settings.db_path)
    db.init()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Meeting to Jira (local)", version="0.1.0")
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

    _register_routes(app)
    return app


# ---------- dependencies ----------


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def _code(settings: Annotated[Settings, Depends(_settings)]) -> CodeProvider:
    return get_code_provider(settings)


def _jira(settings: Annotated[Settings, Depends(_settings)]) -> JiraProvider:
    return get_jira_provider(settings)


SettingsDep = Annotated[Settings, Depends(_settings)]
DbDep = Annotated[Database, Depends(_db)]
CodeDep = Annotated[CodeProvider, Depends(_code)]
JiraDep = Annotated[JiraProvider, Depends(_jira)]


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

    @app.get("/runs")
    async def list_runs(db: DbDep) -> list[Run]:
        return db.list_runs()
