"""What the task shows of its Swift build (MCP detail, tasks API) and the guards of the retry."""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import apple, main, workflow
from app.api import deps, tasks as tasks_api
from app.api.errors import ApiError, api_error
from app.mcp_server import tools as mcp_tools
from app.errors import ErrorCode, WorkflowError
from app.models import AppleJobStatus, Base, Conversation, Project, Room, Task, TaskStatus

HEAD = "b" * 40
ERROR_LINE = "A.swift:3:5: error: cannot find 'x' in scope"


@pytest_asyncio.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'visibility.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(sessions):
    async with sessions() as s:
        yield s


@pytest_asyncio.fixture
async def client(sessions):
    async def per_request_session():
        async with sessions() as s:
            yield s

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error)
    app.add_exception_handler(WorkflowError, main.workflow_error)
    app.include_router(tasks_api.router, prefix="/api")
    app.dependency_overrides[deps.get_session] = per_request_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def add_task(db, platform: str, task_status=TaskStatus.review, pr_number: int | None = 12) -> tuple[Project, Task]:
    project = Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1, platform=platform)
    db.add(project)
    await db.flush()
    room = Room(project_id=project.id, name="r")
    db.add(room)
    await db.flush()
    conversation = Conversation(room_id=room.id, title="c")
    db.add(conversation)
    await db.flush()
    task = Task(
        project_id=project.id, room_id=room.id, conversation_id=conversation.id, title="t", status=task_status,
        branch="feat/1-x", pr_number=pr_number,
    )  # fmt: skip
    db.add(task)
    await db.commit()
    return project, task


async def failed_build(db, task) -> None:
    job = await apple.enqueue_job(db, task.project_id, task.branch, HEAD, task.id)
    job.status, job.log_excerpt = AppleJobStatus.failed, f"Compiling\n{ERROR_LINE}\n"
    await db.commit()


# --- Detail ------------------------------------------------------------------------


async def test_the_detail_of_an_apple_task_carries_its_latest_build(db):
    project, task = await add_task(db, "apple")
    await failed_build(db, task)
    detail = await workflow.task_detail(db, project.id, task.id)
    assert (detail["apple_build"]["status"], detail["apple_build"]["errors"]) == ("failed", [ERROR_LINE])


async def test_the_detail_of_a_generic_task_has_no_build(db):
    project, task = await add_task(db, "generic")
    assert "apple_build" not in await workflow.task_detail(db, project.id, task.id)


async def test_the_api_detail_of_an_apple_task_carries_its_latest_build(db, client):
    _, task = await add_task(db, "apple")
    await failed_build(db, task)
    response = await client.get(f"/api/tasks/{task.id}")
    assert response.status_code == status.HTTP_200_OK
    assert (response.json()["apple_build"]["status"], response.json()["apple_build"]["errors"]) == ("failed", [ERROR_LINE])


async def test_the_api_detail_of_a_generic_task_has_no_build(db, client):
    _, task = await add_task(db, "generic")
    assert (await client.get(f"/api/tasks/{task.id}")).json()["apple_build"] is None


# --- Retry -------------------------------------------------------------------------


async def test_retrying_queues_a_new_build_after_an_infra_error(db):
    project, task = await add_task(db, "apple")
    job = await apple.enqueue_job(db, project.id, task.branch, HEAD, task.id)
    job.status = AppleJobStatus.error
    await db.commit()

    await workflow.retry_apple_build(db, project.id, task.id)
    latest = await apple.latest_task_job(db, task.id)
    assert (latest.id != job.id, latest.status) == (True, AppleJobStatus.queued)


async def test_retrying_a_generic_project_is_refused(db):
    project, task = await add_task(db, "generic")
    with pytest.raises(WorkflowError) as error:
        await workflow.retry_apple_build(db, project.id, task.id)
    assert error.value.code == ErrorCode.APPLE_BUILD_NOT_APPLE_PROJECT


@pytest.mark.parametrize(("task_status", "pr_number"), [(TaskStatus.in_progress, 12), (TaskStatus.review, None)])
async def test_retrying_without_a_pull_request_in_review_is_refused(db, task_status, pr_number):
    project, task = await add_task(db, "apple", task_status, pr_number)
    with pytest.raises(WorkflowError) as error:
        await workflow.retry_apple_build(db, project.id, task.id)
    assert error.value.code == ErrorCode.TASK_NO_PULL_REQUEST


async def test_the_api_refuses_to_retry_a_build_that_is_not_an_infra_error(db, client):
    _, task = await add_task(db, "apple")
    await failed_build(db, task)
    response = await client.post(f"/api/tasks/{task.id}/apple-build/retry")
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == ErrorCode.APPLE_BUILD_NOT_RETRYABLE


async def test_the_api_refuses_to_retry_a_build_on_a_generic_project(db, client):
    _, task = await add_task(db, "generic")
    response = await client.post(f"/api/tasks/{task.id}/apple-build/retry")
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["code"] == ErrorCode.APPLE_BUILD_NOT_APPLE_PROJECT


async def test_the_mcp_tool_tells_the_lead_the_project_is_not_an_apple_one(db, sessions, monkeypatch):
    project, task = await add_task(db, "generic")
    monkeypatch.setattr(mcp_tools, "SessionLocal", sessions)
    monkeypatch.setattr(mcp_tools, "current_caller", lambda _ctx: SimpleNamespace(project_id=project.id))
    with pytest.raises(ToolError, match="not an Apple project"):
        await mcp_tools.retry_apple_build(None, task.id)
