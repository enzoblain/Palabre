from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import models  # noqa: F401 (registers tables)
from app import services
from app.api import catalog, conversations, monitoring, projects, rooms, settings as app_settings, tasks
from app.api.deps import require_admin
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.github import GitHubError
from app.mcp_server.auth import AgentAuthMiddleware
from app.mcp_server import tools  # noqa: F401 (registers the tools)
from app.mcp_server.server import mcp
from app.orchestrator.dispatcher import orchestrator
from app.services import WorkflowError

# Mounted under /mcp, so the endpoint path inside the sub-app is "/".
# host=127.0.0.1 keeps DNS rebinding protection: agents run in the backend container.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/", json_response=True, stateless_http=True, host="127.0.0.1"
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # TODO: Alembic migrations
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        await services.load_app_settings(s)
    async with mcp.session_manager.run():
        if settings.orchestrator_enabled:
            await orchestrator.start()
        try:
            yield
        finally:
            await orchestrator.stop()
    await engine.dispose()


app = FastAPI(title="Palabre", lifespan=lifespan)
# The API is authenticated by a bearer token, not cookies: any origin may call it
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.exception_handler(WorkflowError)
async def workflow_error(_: Request, exc: WorkflowError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(GitHubError)
async def github_error(_: Request, exc: GitHubError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=502)


# REST API for the boss
for router in (
    app_settings.router, catalog.router, projects.router, rooms.router, conversations.router, tasks.router,
    monitoring.router,
):
    app.include_router(router, prefix="/api", dependencies=[Depends(require_admin)])


# Agents reach it at http://127.0.0.1:8000/mcp/ (written into each run's --mcp-config)
app.mount("/mcp", AgentAuthMiddleware(mcp_app))
