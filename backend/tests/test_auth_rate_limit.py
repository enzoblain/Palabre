"""Failed API authentications are throttled per IP."""

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.config import settings


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr(settings, "auth_max_failures", 3)
    deps._failures.clear()
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(deps.require_admin)])
    async def ping():
        return {}

    async with AsyncClient(transport=ASGITransport(app=app, client=("1.1.1.1", 1)), base_url="http://t") as c:
        c.app = app
        yield c
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


async def test_lockout_is_per_ip_and_logged(client, caplog):
    for _ in range(3):
        await client.get("/ping")
    assert "1.1.1.1 locked out" in caplog.text and "Bearer" not in caplog.text
    other = AsyncClient(transport=ASGITransport(app=client.app, client=("2.2.2.2", 1)), base_url="http://t")
    async with other:
        good = {"Authorization": f"Bearer {settings.admin_token}"}
        assert (await other.get("/ping", headers=good)).status_code == 200


async def test_expired_entries_are_swept(client, monkeypatch):
    monkeypatch.setattr(deps, "_SWEEP_ABOVE", 2)
    monkeypatch.setattr(settings, "auth_fail_window_seconds", 0)
    for i in range(5):
        deps._failures[f"10.0.0.{i}"] = [0.0]
    await client.get("/ping")
    assert list(deps._failures) == ["1.1.1.1"]


async def test_x_real_ip_only_trusted_from_the_proxy(client, monkeypatch):
    monkeypatch.setattr(deps, "_proxy_cache", (float("inf"), {"1.1.1.1"}))
    for i in range(3):
        await client.get("/ping", headers={"X-Real-IP": f"9.9.9.{i}"})
    # Each browser behind the proxy has its own bucket: nobody is locked out yet
    good = {"Authorization": f"Bearer {settings.admin_token}", "X-Real-IP": "8.8.8.8"}
    assert (await client.get("/ping", headers=good)).status_code == 200
    # A direct caller (not the proxy) cannot pick its bucket with a forged header
    monkeypatch.setattr(deps, "_proxy_cache", (float("inf"), set()))
    deps._failures.clear()
    for i in range(3):
        await client.get("/ping", headers={"X-Real-IP": f"9.9.9.{i}"})
    assert (await client.get("/ping", headers={"X-Real-IP": "7.7.7.7", "Authorization": f"Bearer {settings.admin_token}"})).status_code == 429
