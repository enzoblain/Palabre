"""API errors carry a stable `code` next to the English `detail`, with unchanged statuses."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app import github
from app.api import deps
from app.api.errors import NOT_FOUND, ApiError, ErrorCode, api_error, validation_error
from app.config import settings
from app.github import GitHubError
from app.errors import WorkflowError
from fastapi.exceptions import RequestValidationError


class Body(BaseModel):
    n: int


@pytest_asyncio.fixture
async def client():
    deps._failures.clear()
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error)
    app.add_exception_handler(RequestValidationError, validation_error)

    @app.get("/secure", dependencies=[Depends(deps.require_admin)])
    async def secure():
        return {}

    @app.get("/missing")
    async def missing():
        raise ApiError(404, ErrorCode.PROJECT_NOT_FOUND, "Project 1 not found")

    @app.post("/body")
    async def body(b: Body):
        return {}

    async with AsyncClient(transport=ASGITransport(app=app, client=("2.2.2.2", 1)), base_url="http://t") as c:
        yield c
    deps._failures.clear()


async def test_error_has_code_and_detail(client):
    r = await client.get("/missing")
    assert r.status_code == 404
    assert r.json() == {"detail": "Project 1 not found", "code": "project_not_found"}


async def test_auth_error_code(client):
    r = await client.get("/secure", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert r.json() == {"detail": "Invalid token", "code": "auth_invalid_token"}


async def test_lockout_keeps_headers(client):
    for _ in range(settings.auth_max_failures):
        await client.get("/secure", headers={"Authorization": "Bearer nope"})
    r = await client.get("/secure", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 429 and r.json()["code"] == "auth_locked" and "Retry-After" in r.headers


async def test_validation_error_code(client):
    r = await client.post("/body", json={"n": "x"})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error" and isinstance(r.json()["detail"], list)


def test_codes_are_snake_case_and_unique():
    assert all(c.value == c.name.lower() for c in ErrorCode)
    assert set(NOT_FOUND.values()) <= set(ErrorCode)


API_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api.ts"
ERROR_CODES_BLOCK = re.compile(r"export const ERROR_CODES = \[(.*?)\] as const", re.DOTALL)


def test_frontend_error_codes_match_backend():
    block = ERROR_CODES_BLOCK.search(API_TS.read_text())
    assert block, f"ERROR_CODES array not found in {API_TS}"
    frontend = set(re.findall(r'"([^"]+)"', block.group(1)))
    backend = {c.value for c in ErrorCode}
    assert frontend == backend, (
        f"api.ts ERROR_CODES is out of sync with ErrorCode: "
        f"missing in api.ts: {sorted(backend - frontend)}; extra in api.ts: {sorted(frontend - backend)}"
    )


class _NoRows:
    """A session where every lookup misses."""

    async def get(self, *_args, **_kwargs):
        return None

    async def scalar(self, *_args, **_kwargs):
        return None


@pytest_asyncio.fixture
async def real_client(monkeypatch):
    from app.db import get_session
    from app.main import app

    async def no_rows():
        yield _NoRows()

    deps._failures.clear()
    app.dependency_overrides[get_session] = no_rows
    headers = {"Authorization": f"Bearer {settings.admin_token}"}
    transport = ASGITransport(app=app, client=("3.3.3.3", 1))
    async with AsyncClient(transport=transport, base_url="http://t", headers=headers) as c:
        yield c
    app.dependency_overrides.pop(get_session, None)
    deps._failures.clear()


async def test_real_app_unknown_project(real_client):
    r = await real_client.get("/api/projects/999")
    assert r.status_code == 404
    assert r.json() == {"detail": "Project 999 not found", "code": "project_not_found"}


async def test_real_app_requires_token(real_client):
    r = await real_client.get("/api/projects/1", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["code"] == "auth_invalid_token"


async def test_real_app_validation_error(real_client):
    r = await real_client.put("/api/projects/1/mode", json={})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (WorkflowError("nope"), 409, "workflow_error"),
        (GitHubError("boom"), 502, "github_error"),
        (WorkflowError("blocked", code=ErrorCode.MERGE_BLOCKED), 409, "merge_blocked"),
        (GitHubError("no token", ErrorCode.GITHUB_NOT_CONFIGURED), 502, "github_not_configured"),
    ],
)
async def test_real_app_domain_errors(real_client, monkeypatch, exc, status, code):
    from app.api import tasks

    async def load_task(*_a, **_k):
        return SimpleNamespace(id=1, project_id=1)

    async def merge_task(*_a, **_k):
        raise exc

    monkeypatch.setattr(tasks, "load_task", load_task)
    monkeypatch.setattr(tasks.workflow, "merge_task", merge_task)
    r = await real_client.post("/api/tasks/1/merge", json={})
    assert r.status_code == status
    assert r.json() == {"detail": str(exc), "code": code}


async def test_get_or_404_falls_back_to_generic_code():
    class Unmapped:
        pass

    with pytest.raises(ApiError) as e:
        await deps.get_or_404(_NoRows(), Unmapped, 1)
    assert e.value.status_code == 404 and e.value.code == ErrorCode.NOT_FOUND


async def test_real_app_personality_code(real_client, monkeypatch):
    from app.api import projects as api_projects

    async def get_or_404(_s, _model, _id):
        return SimpleNamespace(id=1, project_id=1, kind="company")

    monkeypatch.setattr(api_projects, "get_or_404", get_or_404)
    r = await real_client.patch("/api/employees/1", json={"traits": {"nope": 1}})
    assert r.status_code == 409
    assert r.json()["code"] == "invalid_personality"


def test_github_error_never_leaks_credentials(monkeypatch):
    import base64

    monkeypatch.setattr(settings, "github_token", "ghp_secret123")
    basic = base64.b64encode(b"x-access-token:ghp_secret123").decode()
    err = GitHubError(f"fatal: https://x-access-token:ghp_secret123@github.com/o/r failed AUTHORIZATION: basic {basic}")
    assert "ghp_secret123" not in str(err) and basic not in str(err)
    assert "https://***@github.com/o/r" in str(err)
    assert GitHubError("x").code == ErrorCode.GITHUB_ERROR


async def test_real_app_production_branch_code(real_client, monkeypatch):
    from app.api import projects as api_projects

    async def project(_s, _id):
        return SimpleNamespace(id=1, kind="company", default_branch="dev")

    async def change_branch(*_a, **_k):
        raise WorkflowError("main is the production branch", code=ErrorCode.PRODUCTION_BRANCH_BOSS_ONLY)

    monkeypatch.setattr(api_projects, "_project", project)
    monkeypatch.setattr(api_projects.projects, "change_branch", change_branch)
    r = await real_client.put("/api/projects/1/branch", json={"branch": "main"})
    assert r.status_code == 409
    assert r.json() == {"detail": "main is the production branch", "code": "production_branch_boss_only"}


async def test_real_app_custom_team_with_two_leads_is_refused(real_client, monkeypatch):
    async def reachable_branch(*_args):
        return "main"

    monkeypatch.setattr(github, "resolve_branch", reachable_branch)
    team = [{"name": "Ada", "roles": ["lead"]}, {"name": "Bob", "roles": ["lead"]}]
    r = await real_client.post("/api/projects", json={"name": "P", "repo_url": "https://github.com/o/r", "employees": team})
    assert r.status_code == 422 and r.json()["code"] == "invalid_team_permissions"
