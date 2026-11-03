"""Device sessions: pairing, sliding expiry, revocation, invalid tokens and the failure counter."""

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app import devices
from app.api import auth, deps
from app.api.errors import ApiError, api_error
from app.config import settings
from app.models import DeviceSession

NOW = datetime(2030, 1, 1, tzinfo=UTC)


class FakeDeviceStore:
    """Rows shared by every FakeDeviceSession, like the table they stand for."""

    def __init__(self) -> None:
        self.rows: list[DeviceSession] = []
        self.commits = 0
        self.ids = count(1)


class FakeDeviceSession:
    """Just enough of AsyncSession for devices.py and the /auth/devices routes."""

    def __init__(self, store: FakeDeviceStore) -> None:
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    def add(self, row: DeviceSession) -> None:
        row.id = next(self.store.ids)
        self.store.rows.append(row)

    async def scalar(self, query):
        wanted = next(iter(query.compile().params.values()))
        return next((r for r in self.store.rows if r.token_hash == wanted), None)

    async def scalars(self, _query):
        rows = sorted(self.store.rows, key=lambda r: (r.created_at, r.id), reverse=True)
        return type("Result", (), {"all": lambda _self: rows})()

    async def get(self, _model, device_id):
        return next((r for r in self.store.rows if r.id == device_id), None)

    async def delete(self, row: DeviceSession) -> None:
        self.store.rows.remove(row)

    async def commit(self) -> None:
        self.store.commits += 1


@pytest.fixture
def store(monkeypatch):
    fake = FakeDeviceStore()
    monkeypatch.setattr(deps, "SessionLocal", lambda: FakeDeviceSession(fake))
    return fake


@pytest_asyncio.fixture
async def client(store):
    deps._failures.clear()
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error)
    app.include_router(auth.router, prefix="/api")
    app.dependency_overrides[deps.get_session] = lambda: FakeDeviceSession(store)

    @app.get("/ping", dependencies=[Depends(deps.require_admin)])
    async def ping():
        return {}

    async with AsyncClient(transport=ASGITransport(app=app, client=("1.1.1.1", 1)), base_url="http://t") as c:
        yield c
    deps._failures.clear()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def pair(client, name: str = "Pixel") -> dict:
    r = await client.post("/api/auth/devices", json={"name": name}, headers=bearer(settings.admin_token))
    assert r.status_code == 201
    return r.json()


async def test_pairing_returns_a_prefixed_token_that_opens_the_api(client):
    device = await pair(client)
    assert device["token"].startswith("pdev_") and device["name"] == "Pixel"
    assert (await client.get("/ping", headers=bearer(device["token"]))).status_code == 200


async def test_token_is_stored_hashed_only(client, store):
    device = await pair(client)
    row = store.rows[0]
    assert row.token_hash == devices.hash_device_token(settings.admin_token, device["token"])
    assert device["token"] != row.token_hash


async def test_listing_never_exposes_tokens(client):
    device = await pair(client)
    listed = (await client.get("/api/auth/devices", headers=bearer(settings.admin_token))).json()
    assert [d["name"] for d in listed] == ["Pixel"]
    assert "token" not in listed[0] and "token_hash" not in listed[0]
    assert device["token"] not in str(listed)


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
async def test_pairing_rejects_invalid_names(client, name):
    r = await client.post("/api/auth/devices", json={"name": name}, headers=bearer(settings.admin_token))
    assert r.status_code == 422


async def test_pairing_requires_the_raw_admin_token(client):
    device = await pair(client)
    r = await client.post("/api/auth/devices", json={"name": "Other"}, headers=bearer(device["token"]))
    assert r.status_code == 401


async def test_pairing_attempts_are_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_max_failures", 2)
    for _ in range(2):
        r = await client.post("/api/auth/devices", json={"name": "A"}, headers=bearer("wrong"))
        assert r.status_code == 401
    r = await client.post("/api/auth/devices", json={"name": "A"}, headers=bearer(settings.admin_token))
    assert r.status_code == 429


async def test_revoked_device_is_refused_immediately(client):
    device = await pair(client)
    r = await client.delete(f"/api/auth/devices/{device['id']}", headers=bearer(settings.admin_token))
    assert r.status_code == 204
    assert (await client.get("/ping", headers=bearer(device["token"]))).status_code == 401


async def test_revoking_an_unknown_device_is_404(client):
    r = await client.delete("/api/auth/devices/99", headers=bearer(settings.admin_token))
    assert r.status_code == 404 and r.json()["code"] == "device_not_found"


async def test_listing_and_revoking_need_authentication(client):
    assert (await client.get("/api/auth/devices")).status_code == 401
    assert (await client.delete("/api/auth/devices/1", headers=bearer("nope"))).status_code == 401


async def test_unknown_device_token_counts_as_a_failure(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_max_failures", 2)
    for _ in range(2):
        assert (await client.get("/ping", headers=bearer("pdev_bogus"))).status_code == 401
    assert (await client.get("/ping", headers=bearer("pdev_bogus"))).status_code == 429


async def test_token_is_refused_after_the_admin_token_changes(client, monkeypatch):
    device = await pair(client)
    monkeypatch.setattr(settings, "admin_token", "another-admin-token-" + "y" * 32)
    assert (await client.get("/ping", headers=bearer(device["token"]))).status_code == 401


async def test_non_prefixed_token_never_reaches_the_database(client, monkeypatch):
    def forbidden():
        raise AssertionError("database touched")

    monkeypatch.setattr(deps, "SessionLocal", forbidden)
    assert (await client.get("/ping", headers=bearer("1.bogus"))).status_code == 401


async def test_expired_device_is_refused_and_removed(store):
    s = FakeDeviceSession(store)
    _, token = await devices.create_device_session(s, "secret", "Pixel", 100, now=NOW)
    assert not await devices.authenticate_device(s, "secret", token, 100, now=NOW + timedelta(seconds=100))
    assert store.rows == []


async def test_use_slides_the_expiry(store):
    s = FakeDeviceSession(store)
    _, token = await devices.create_device_session(s, "secret", "Pixel", 1000, now=NOW)
    later = NOW + timedelta(seconds=900)
    assert await devices.authenticate_device(s, "secret", token, 1000, now=later)
    assert store.rows[0].expires_at == later + timedelta(seconds=1000)
    assert await devices.authenticate_device(s, "secret", token, 1000, now=NOW + timedelta(seconds=1800))


async def test_writes_are_limited_to_one_per_minute(store):
    s = FakeDeviceSession(store)
    _, token = await devices.create_device_session(s, "secret", "Pixel", 1000, now=NOW)
    commits = store.commits
    for seconds in (1, 20, 59):
        assert await devices.authenticate_device(s, "secret", token, 1000, now=NOW + timedelta(seconds=seconds))
    assert store.commits == commits
    assert await devices.authenticate_device(s, "secret", token, 1000, now=NOW + timedelta(seconds=60))
    assert store.commits == commits + 1


async def test_web_session_token_is_unchanged(client):
    token = (await client.post("/api/auth/session", headers=bearer(settings.admin_token))).json()["token"]
    assert (await client.get("/ping", headers=bearer(token))).status_code == 200
