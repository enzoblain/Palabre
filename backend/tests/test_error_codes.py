"""API errors carry a stable `code` next to the English `detail`, with unchanged statuses."""

import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.api import deps
from app.api.errors import NOT_FOUND, ApiError, ErrorCode, api_error, validation_error
from app.config import settings
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
