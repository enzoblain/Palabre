"""CORS headers are sent only to the configured origins."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _preflight(client: AsyncClient, origin: str):
    return await client.options(
        "/api/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"}
    )


def test_default_origins_are_not_wildcard():
    assert "*" not in settings.cors_origins


@pytest.mark.parametrize("origin", ["http://localhost:1420", "tauri://localhost"])
async def test_listed_origin_is_allowed(client, origin):
    response = await _preflight(client, origin)
    assert response.headers["access-control-allow-origin"] == origin


async def test_unlisted_origin_gets_no_allow_origin_header(client):
    response = await _preflight(client, "https://evil.example")
    assert "access-control-allow-origin" not in response.headers
