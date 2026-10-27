from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401 (registers tables)
from app.config import settings
from app.db import Base, engine
from app.mcp_server.auth import AgentAuthMiddleware
from app.mcp_server import tools  # noqa: F401 (registers the tools)
from app.mcp_server.server import mcp
from app.orchestrator.dispatcher import orchestrator

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
    async with mcp.session_manager.run():
        if settings.orchestrator_enabled:
            await orchestrator.start()
        try:
            yield
        finally:
            await orchestrator.stop()
    await engine.dispose()


app = FastAPI(title="Palabre", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# Agents reach it at http://127.0.0.1:8000/mcp/ (written into each run's --mcp-config)
app.mount("/mcp", AgentAuthMiddleware(mcp_app))
