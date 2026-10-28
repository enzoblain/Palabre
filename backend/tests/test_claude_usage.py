"""Claude quota usage: parsing, per-account errors, cache and token hygiene (usage API mocked)."""

import asyncio
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
    "seven_day_oauth_apps": {"utilization": 3, "resets_at": None},
    "extra": {"foo": 1},
}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(accounts.settings, "claude_code_oauth_tokens", "secret-one|secret-two")
    claude_usage._cache.clear()
    claude_usage._locks.clear()


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
    assert "rejected" in out.accounts[0].error and out.accounts[0].session is None
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


async def test_concurrent_refreshes_call_endpoint_once_per_account(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request.headers["authorization"])
        await asyncio.sleep(0.05)
        return httpx.Response(200, json=PAYLOAD)

    mock_api(monkeypatch, handler)
    await asyncio.gather(*(claude_usage.fetch_all() for _ in range(5)))
    assert sorted(calls) == ["Bearer secret-one", "Bearer secret-two"]


def test_http_libraries_never_log_at_debug():
    for name in ("httpx", "httpcore"):
        assert not logging.getLogger(name).isEnabledFor(logging.DEBUG)


# Real shape of the usage endpoint's answer (extra keys included)
REAL_PAYLOAD = {
    "five_hour": {"utilization": 37.0, "resets_at": "2026-10-28T23:00:00.123456+00:00"},
    "seven_day": {"utilization": 12.0, "resets_at": "2026-11-03T08:00:00.123456+00:00"},
    "seven_day_oauth_apps": None,
    "seven_day_opus": None,
    "seven_day_sonnet": {"utilization": 4.0, "resets_at": "2026-11-03T08:00:00.123456+00:00"},
    "iguana_necktie": None,
    "extra_usage": {"is_enabled": False, "monthly_limit": None, "used_credits": None, "utilization": None},
}
SCOPE_ERROR = {
    "type": "error",
    "error": {"type": "permission_error", "message": "OAuth token does not meet scope requirement user:profile"},
}


async def test_real_format_end_to_end(monkeypatch):
    mock_api(monkeypatch, lambda request: httpx.Response(200, json=REAL_PAYLOAD))
    a = (await get_quota()).accounts[0]
    assert (a.session.used_percent, a.week.used_percent) == (37.0, 12.0)
    assert [m.model for m in a.models] == ["sonnet"]


async def test_scope_error_falls_back_to_rate_limit_headers(monkeypatch):
    def handler(request):
        if request.url.path == "/api/oauth/usage":
            return httpx.Response(403, json=SCOPE_ERROR)
        assert request.headers["authorization"].startswith("Bearer secret-")
        return httpx.Response(
            200,
            json={"type": "message"},
            headers={
                "anthropic-ratelimit-unified-5h-utilization": "0.37",
                "anthropic-ratelimit-unified-5h-reset": "1793228400",
                "anthropic-ratelimit-unified-7d-utilization": "0.12",
                "anthropic-ratelimit-unified-7d-reset": "1793865600",
            },
        )

    mock_api(monkeypatch, handler)
    a = (await get_quota()).accounts[0]
    assert a.error is None and a.session.used_percent == pytest.approx(37) and a.week.used_percent == pytest.approx(12)
    assert a.session.resets_at.year == 2026


async def test_scope_error_without_fallback_is_readable(monkeypatch, caplog):
    mock_api(monkeypatch, lambda request: httpx.Response(403, json=SCOPE_ERROR))
    with caplog.at_level(logging.DEBUG):
        out = await get_quota()
    assert "scope requirement user:profile" in out.accounts[0].error
    assert "secret" not in caplog.text and "secret" not in out.model_dump_json()
