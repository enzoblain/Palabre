import gzip
import json

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from app import anthropic_proxy
from app.config import settings
from app.mcp_server import run_tokens

ACCOUNT_TOKEN = "sk-ant-oat-account"


@pytest.fixture
def upstream(monkeypatch):
    """The Anthropic API, replaced by a recorder."""
    calls: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"{}"))

    monkeypatch.setattr(
        anthropic_proxy, "_client", httpx.AsyncClient(base_url=settings.anthropic_api_url, transport=httpx.MockTransport(answer))
    )
    return calls


@pytest.fixture
def run_token():
    token = run_tokens.issue(1)
    run_tokens.bind_credential(token, ACCOUNT_TOKEN)
    yield token
    run_tokens.revoke(token)


async def _send(path: str, token: str, **request_kwargs) -> httpx.Response:
    app = FastAPI()
    app.include_router(anthropic_proxy.router)
    headers = {"Authorization": f"Bearer {token}"} | request_kwargs.pop("headers", {})
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(f"/anthropic/{path}", headers=headers, **request_kwargs)


async def _post(path: str, body: dict | None, token: str, headers: dict[str, str] | None = None) -> httpx.Response:
    return await _send(path, token, json=body, headers=headers or {})


async def test_account_token_replaces_the_run_token(upstream, run_token):
    response = await _post("v1/messages", {"tools": [{"name": "Read", "input_schema": {}}]}, run_token, {"x-api-key": "leak"})
    assert response.status_code == 200
    (sent,) = upstream
    assert sent.headers["authorization"] == f"Bearer {ACCOUNT_TOKEN}"
    assert "x-api-key" not in sent.headers and run_token not in str(sent.headers)
    assert str(sent.url) == "https://api.anthropic.com/v1/messages"


async def test_unknown_or_finished_run_is_refused(upstream, run_token):
    assert (await _post("v1/messages", {}, "guess")).status_code == 401
    run_tokens.revoke(run_token)
    assert (await _post("v1/messages", {}, run_token)).status_code == 401
    assert upstream == []


@pytest.mark.parametrize("tool", [{"type": "web_fetch_20250910", "name": "web_fetch"}, {"type": "code_execution_20250522"}])
async def test_unexpected_server_tools_are_refused(upstream, run_token, tool):
    response = await _post("v1/messages", {"tools": [{"name": "Read"}, tool]}, run_token)
    assert response.status_code == 403
    assert upstream == []


async def test_remote_mcp_servers_are_refused(upstream, run_token):
    assert (await _post("v1/messages", {"mcp_servers": [{"url": "https://evil"}]}, run_token)).status_code == 403
    assert upstream == []


async def test_web_search_is_allowed_by_default(upstream, run_token):
    assert (await _post("v1/messages", {"tools": [{"type": "web_search_20250305", "name": "web_search"}]}, run_token)).status_code == 200


async def test_other_paths_are_refused(upstream, run_token):
    assert (await _post("v1/files", {}, run_token)).status_code == 403
    assert (await _post("v1/messages/../files", {}, run_token)).status_code == 403
    assert upstream == []


async def test_non_json_body_is_refused(upstream, run_token):
    assert (await _send("v1/messages", run_token, content=b"nope")).status_code == 400
    assert upstream == []


async def test_encoded_request_body_is_refused(upstream, run_token):
    response = await _send("v1/messages", run_token, content=b"{}", headers={"content-encoding": "gzip"})
    assert response.status_code == 415
    assert upstream == []


async def test_oversized_body_is_refused(upstream, run_token, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_max_body_bytes", 4)
    assert (await _send("v1/messages", run_token, content=b'{"a": 1}')).status_code == 413
    assert upstream == []


async def test_compressed_upstream_answer_reaches_the_client_decoded(monkeypatch, run_token):
    payload = {"id": "msg_1"}
    compressed = gzip.compress(json.dumps(payload).encode())
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-encoding": "gzip"}, content=compressed)
    )
    monkeypatch.setattr(anthropic_proxy, "_client", httpx.AsyncClient(base_url=settings.anthropic_api_url, transport=transport))
    response = await _post("v1/messages", {}, run_token)
    assert response.json() == payload


def test_credential_lives_with_the_run():
    token = run_tokens.issue(1)
    run_tokens.bind_credential(token, ACCOUNT_TOKEN)
    assert run_tokens.credential_of(token) == ACCOUNT_TOKEN
    run_tokens.revoke(token)
    assert run_tokens.credential_of(token) is None
