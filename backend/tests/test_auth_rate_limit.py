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
    caplog.set_level("WARNING", logger="app.api.deps")
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


async def _seen_ip(peer, xff):
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    seen = []

    async def app(scope, receive, send):
        seen.append(scope["client"][0])

    wrapped = ProxyHeadersMiddleware(app, trusted_hosts="172.29.0.2")
    scope = {"type": "http", "client": (peer, 1), "headers": [(b"x-forwarded-for", xff.encode())]}
    await wrapped(scope, None, None)
    return seen[0]


async def test_forwarded_for_only_trusted_from_web_container():
    assert await _seen_ip("172.29.0.2", "9.9.9.9") == "9.9.9.9"
    assert await _seen_ip("203.0.113.5", "9.9.9.9") == "203.0.113.5"
