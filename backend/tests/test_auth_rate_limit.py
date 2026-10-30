"""Failed API authentications are throttled per IP."""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.config import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "auth_max_failures", 3)
    deps._failures.clear()
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(deps.require_admin)])
    async def ping():
        return {}

    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://t")
    deps._failures.clear()


async def test_repeated_failures_get_429_even_with_valid_token(client):
    bad = {"Authorization": "Bearer nope"}
    good = {"Authorization": f"Bearer {settings.admin_token}"}
    assert (await client.get("/ping", headers=good)).status_code == 200
    for _ in range(3):
        assert (await client.get("/ping", headers=bad)).status_code == 401
    r = await client.get("/ping", headers=bad)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert (await client.get("/ping", headers=good)).status_code == 429


async def test_failures_expire(client, monkeypatch):
    for _ in range(3):
        await client.get("/ping")
    assert (await client.get("/ping")).status_code == 429
    monkeypatch.setattr(settings, "auth_fail_window_seconds", 0)
    good = {"Authorization": f"Bearer {settings.admin_token}"}
    assert (await client.get("/ping", headers=good)).status_code == 200
