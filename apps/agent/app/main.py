import logging

from fastapi import APIRouter, Depends, FastAPI

from app.config import get_settings
from app.security import require_service_token


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="mtj-agent",
        # Internal service: no public docs.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    # All functional routes go on this router; it is protected by the service token.
    internal = APIRouter(dependencies=[Depends(require_service_token)])

    @internal.get("/whoami")
    async def whoami() -> dict[str, str]:
        return {"caller": "api"}

    app.include_router(internal)
    return app


app = create_app()
