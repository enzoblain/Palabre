"""FastAPI app: startup, API routers, MCP server and scheduler."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import models  # noqa: F401 (registers tables)
from app import agent_pool, anthropic_proxy, egress_proxy, services
from app.projects import backfill_relayed_escalations, drop_generic_rooms, ensure_all_directions, migrate_inbox, normalize_repo_urls, refresh_permissions
from app.api import auth, catalog, conversations, monitoring, projects, rooms, settings as app_settings, tasks
from app.api.deps import require_admin
from app.api.errors import ApiError, api_error, validation_error
from app.config import removed_settings_present, settings
from app.db import SessionLocal, engine, upgrade_schema
from app.github import GitHubError
from app.worktrees import remove_stale_desks
from app.hardening import make_non_dumpable
from app.mcp_server.auth import AgentAuthMiddleware
from app.mcp_server import tools  # noqa: F401 (registers the tools)
from app.mcp_server.server import mcp
from app.orchestrator.dispatcher import orchestrator
from app.errors import WorkflowError

log = logging.getLogger(__name__)

# Before any agent runs: they share the backend's uid and could read its environ
make_non_dumpable()

# Mounted under /mcp, so the endpoint path inside the sub-app is "/".
# host=127.0.0.1 keeps DNS rebinding protection: agents run in the backend container.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/", json_response=True, host="127.0.0.1",
    # A session must outlive its run: an expired one would force a re-initialize
    session_idle_timeout=settings.agent_timeout_s + 300,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    for name in removed_settings_present():
        log.warning("%s is set but no longer exists: it is ignored, you can remove it", name)
    if not settings.agent_user:
        log.warning(
            "AGENT_USER is empty: agents run as the backend's own user and can read its "
            "environment and files. Fine for the desktop app or local development, not for a server."
        )
    agent_pool.check()
    # TODO: Alembic migrations
    async with engine.begin() as conn:
        await conn.run_sync(upgrade_schema)
    async with SessionLocal() as s:
        await services.load_app_settings(s)
        await refresh_permissions(s)
        await ensure_all_directions(s)
        await drop_generic_rooms(s)
        await migrate_inbox(s)
        await normalize_repo_urls(s)
        await backfill_relayed_escalations(s)
    await remove_stale_desks()
    proxy = await egress_proxy.start() if settings.agent_user else None
    async with mcp.session_manager.run():
        if settings.orchestrator_enabled:
            await orchestrator.start()
        try:
            yield
        finally:
            await orchestrator.stop()
            if proxy:
                proxy.close()
    await anthropic_proxy.close_client()
    await engine.dispose()


app = FastAPI(title="Palabre", lifespan=lifespan)
# Only the configured origins get CORS headers; the API itself is authenticated by a bearer token
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


app.add_exception_handler(ApiError, api_error)
app.add_exception_handler(RequestValidationError, validation_error)


@app.exception_handler(WorkflowError)
async def workflow_error(_: Request, exc: WorkflowError) -> JSONResponse:
    return JSONResponse({"detail": str(exc), "code": exc.code.value}, status_code=409)


@app.exception_handler(GitHubError)
async def github_error(_: Request, exc: GitHubError) -> JSONResponse:
    return JSONResponse({"detail": str(exc), "code": exc.code.value}, status_code=502)


# Login: guarded by its own raw-token-only dependency, so it is mounted apart from the routers below
app.include_router(auth.router, prefix="/api")

# REST API for the boss
for router in (
    app_settings.router, catalog.router, projects.router, rooms.router, conversations.router, tasks.router,
    monitoring.router,
):
    app.include_router(router, prefix="/api", dependencies=[Depends(require_admin)])


# Agents' Claude Code reaches the Anthropic API through it (ANTHROPIC_BASE_URL), authenticated by its run token
app.include_router(anthropic_proxy.router)

# Agents reach it at http://127.0.0.1:8000/mcp/ (written into each run's --mcp-config)
app.mount("/mcp", AgentAuthMiddleware(mcp_app))
