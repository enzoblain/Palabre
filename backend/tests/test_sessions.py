"""Session tokens: signing, expiry, revocation by secret change, and the login endpoint."""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import auth, deps
from app.config import settings
from app.sessions import issue_session_token, verify_session_token

SECRET = "s" * 40


def test_valid_token_is_accepted():
    token, expires_at = issue_session_token(SECRET, 60, now=1000)
    assert expires_at == 1060
    assert verify_session_token(SECRET, token, now=1059)


def test_expired_token_is_refused():
    token, _ = issue_session_token(SECRET, 60, now=1000)
    assert not verify_session_token(SECRET, token, now=1060)


def test_changing_the_secret_revokes_tokens():
    token, _ = issue_session_token(SECRET, 60, now=1000)
    assert not verify_session_token("t" * 40, token, now=1001)


def test_tampered_expiry_is_refused():
    token, _ = issue_session_token(SECRET, 60, now=1000)
    _, signature = token.split(".")
    assert not verify_session_token(SECRET, f"9999999999.{signature}", now=1001)


@pytest.mark.parametrize("junk", ["", "nodot", ".", "abc.def", "12.", "².x", ".sig", "-5.sig"])
def test_malformed_tokens_are_refused(junk):
    assert not verify_session_token(SECRET, junk, now=1)


def test_raw_admin_token_is_not_a_valid_session_token():
    assert not verify_session_token(SECRET, SECRET, now=1)


@pytest.fixture
async def client():
    deps._failures.clear()
    app = FastAPI()
    app.include_router(auth.router, prefix="/api")

    @app.get("/ping", dependencies=[Depends(deps.require_admin)])
    async def ping():
        return {}

    async with AsyncClient(transport=ASGITransport(app=app, client=("1.1.1.1", 1)), base_url="http://t") as c:
        yield c
    deps._failures.clear()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_login_returns_a_token_that_opens_the_api(client):
    r = await client.post("/api/auth/session", headers=bearer(settings.admin_token))
    assert r.status_code == 200
    assert r.json()["token"] != settings.admin_token
    assert (await client.get("/ping", headers=bearer(r.json()["token"]))).status_code == 200


async def test_raw_admin_token_still_opens_the_api(client):
    assert (await client.get("/ping", headers=bearer(settings.admin_token))).status_code == 200


async def test_expired_session_is_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "session_ttl_seconds", 1)
    token = (await client.post("/api/auth/session", headers=bearer(settings.admin_token))).json()["token"]
    monkeypatch.setattr("app.sessions.time.time", lambda: 2e10)
    assert (await client.get("/ping", headers=bearer(token))).status_code == 401


async def test_session_token_cannot_mint_a_session(client):
    token = (await client.post("/api/auth/session", headers=bearer(settings.admin_token))).json()["token"]
    assert (await client.post("/api/auth/session", headers=bearer(token))).status_code == 401


async def test_invalid_session_counts_as_a_failure(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_max_failures", 2)
    for _ in range(2):
        assert (await client.get("/ping", headers=bearer("1.bogus"))).status_code == 401
    assert (await client.get("/ping", headers=bearer("1.bogus"))).status_code == 429
