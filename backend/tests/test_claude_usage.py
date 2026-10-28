"""Claude quota usage: parsing, per-account errors, cache and token hygiene (usage API mocked)."""

import logging

import httpx
import pytest

from app import accounts, claude_usage
from app.api.settings import get_quota

PAYLOAD = {
    "five_hour": {"utilization": 12.0, "resets_at": "2026-10-28T18:00:00+00:00"},
    "seven_day": {"utilization": 40, "resets_at": "2026-11-02T09:00:00+00:00"},
    "seven_day_opus": {"utilization": 55.5, "resets_at": "2026-11-02T09:00:00+00:00"},
    "seven_day_sonnet": None,
    "extra": {"foo": 1},
}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(accounts.settings, "claude_code_oauth_tokens", "secret-one|secret-two")
    claude_usage._cache.clear()


def mock_api(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        claude_usage.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )


async def test_parse_windows(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json=PAYLOAD)

    mock_api(monkeypatch, handler)
    out = await get_quota()
    assert seen == ["Bearer secret-one", "Bearer secret-two"]
    a = out.accounts[0]
    assert (a.session.used_percent, a.week.used_percent) == (12.0, 40)
    assert a.session.resets_at.hour == 18
    assert [(m.model, m.used_percent) for m in a.models] == [("opus", 55.5)]
    assert "secret" not in out.model_dump_json()


async def test_failing_account_does_not_break_others(monkeypatch, caplog):
    def handler(request):
        if request.headers["authorization"] == "Bearer secret-one":
            return httpx.Response(401, json={"error": "bad"})
        return httpx.Response(200, json=PAYLOAD)

    mock_api(monkeypatch, handler)
    with caplog.at_level(logging.DEBUG):
        out = await get_quota()
    assert "401" in out.accounts[0].error and out.accounts[0].session is None
    assert out.accounts[1].error is None and out.accounts[1].session
    assert "secret" not in caplog.text and "secret" not in out.model_dump_json()


async def test_network_error_and_bad_json(monkeypatch):
    def handler(request):
        if request.headers["authorization"] == "Bearer secret-one":
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, content=b"not json")

    mock_api(monkeypatch, handler)
    out = await get_quota()
    assert "timed out" in out.accounts[0].error
    assert out.accounts[1].error


async def test_cache(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=PAYLOAD)

    mock_api(monkeypatch, handler)
    await get_quota()
    await get_quota()
    assert len(calls) == 2  # one per account, second call served from cache
