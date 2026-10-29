"""A run's MCP token only works while the run lives."""

from app.mcp_server import auth, run_tokens


async def test_token_of_a_finished_run_is_refused():
    token = run_tokens.issue(1)
    assert run_tokens.employee_of(token) == 1
    run_tokens.revoke(token)
    assert run_tokens.employee_of(token) is None
    assert await auth.resolve_caller(token, "1", "") is None


async def test_unknown_token_is_refused():
    assert await auth.resolve_caller("guess", "1", "") is None


def test_tokens_are_distinct_per_run():
    assert run_tokens.issue(1) != run_tokens.issue(1)


def test_config_file_is_deleted_on_first_use(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text("{}")
    token = run_tokens.issue(2)
    run_tokens.attach_config(token, path)
    assert run_tokens.employee_of(token) == 2
    assert not path.exists()
    assert run_tokens.employee_of(token) == 2  # later requests still work
    run_tokens.revoke(token)


async def _call(app, token, session_id=None):
    headers = [(b"authorization", f"Bearer {token}".encode())]
    if session_id:
        headers.append((b"mcp-session-id", session_id.encode()))
    status = []

    async def send(message):
        if message["type"] == "http.response.start":
            status.append(message["status"])

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    await app({"type": "http", "headers": headers}, receive, send)
    return status[0]


async def test_token_is_bound_to_its_first_session(monkeypatch):
    caller = auth.Caller(1, 1, 1, 1, None, frozenset())
    alerts = []

    async def fake_resolve(token, conversation, task):
        return caller if run_tokens.employee_of(token) else None

    async def fake_alert(c):
        alerts.append(c)

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"mcp-session-id", b"s1")]})

    monkeypatch.setattr(auth, "resolve_caller", fake_resolve)
    monkeypatch.setattr(auth, "alert_lead", fake_alert)
    app = auth.AgentAuthMiddleware(inner)
    token = run_tokens.issue(1)

    assert await _call(app, token) == 200  # initialize
    assert await _call(app, token, "s1") == 200  # first session keeps working
    assert await _call(app, token) == 403  # second initialize
    assert await _call(app, token, "other") == 403  # foreign session id
    assert len(alerts) == 2
    run_tokens.revoke(token)
    assert await _call(app, token, "s1") == 401


async def test_failed_initialize_does_not_burn_the_token(monkeypatch):
    async def fake_resolve(token, conversation, task):
        return auth.Caller(1, 1, 1, 1, None, frozenset())

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 500, "headers": []})

    monkeypatch.setattr(auth, "resolve_caller", fake_resolve)
    token = run_tokens.issue(1)
    assert await _call(auth.AgentAuthMiddleware(inner), token) == 500
    assert run_tokens.claim_initialize(token)
    run_tokens.revoke(token)
