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
    monkeypatch.setattr(auth.settings, "mcp_session_binding", "enforce")
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
    assert await _call(app, token) == 403  # second initialize: refused, token revoked
    assert len(alerts) == 1
    assert await _call(app, token, "s1") == 401  # the first session dies too
    assert await _call(app, token, "other") == 401  # later attempts: no new alert
    assert len(alerts) == 1


async def test_foreign_session_id_revokes_the_token(monkeypatch):
    monkeypatch.setattr(auth.settings, "mcp_session_binding", "enforce")
    async def fake_resolve(token, conversation, task):
        return auth.Caller(1, 1, 1, 1, None, frozenset()) if run_tokens.employee_of(token) else None

    async def fake_alert(c):
        pass

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"mcp-session-id", b"s1")]})

    monkeypatch.setattr(auth, "resolve_caller", fake_resolve)
    monkeypatch.setattr(auth, "alert_lead", fake_alert)
    app = auth.AgentAuthMiddleware(inner)
    token = run_tokens.issue(1)
    assert await _call(app, token) == 200
    assert await _call(app, token, "other") == 403
    assert await _call(app, token, "s1") == 401


async def test_failed_initialize_does_not_burn_the_token(monkeypatch):
    monkeypatch.setattr(auth.settings, "mcp_session_binding", "enforce")
    async def fake_resolve(token, conversation, task):
        return auth.Caller(1, 1, 1, 1, None, frozenset())

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 500, "headers": []})

    monkeypatch.setattr(auth, "resolve_caller", fake_resolve)
    token = run_tokens.issue(1)
    assert await _call(auth.AgentAuthMiddleware(inner), token) == 500
    assert run_tokens.claim_initialize(token)
    run_tokens.revoke(token)


async def test_warn_mode_logs_and_alerts_once_without_revoking(monkeypatch, caplog):
    monkeypatch.setattr(auth.settings, "mcp_session_binding", "warn")
    alerts = []

    async def fake_resolve(token, conversation, task):
        return auth.Caller(1, 1, 1, 1, None, frozenset()) if run_tokens.employee_of(token) else None

    async def fake_alert(c, refused=True):
        alerts.append(refused)

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"mcp-session-id", b"s1")]})

    monkeypatch.setattr(auth, "resolve_caller", fake_resolve)
    monkeypatch.setattr(auth, "alert_lead", fake_alert)
    app = auth.AgentAuthMiddleware(inner)
    token = run_tokens.issue(1)

    with caplog.at_level("INFO", logger=auth.log.name):
        assert await _call(app, token) == 200
        assert await _call(app, token) == 200  # second initialize: allowed
        assert await _call(app, token) == 200  # third: no new alert
        assert await _call(app, token, "s1") == 200
        assert await _call(app, token, "other") == 200
    assert alerts == [False]
    initializes = [r.getMessage() for r in caplog.records if "MCP initialize" in r.getMessage()]
    assert [m.split(":")[1].split(" of")[0].strip() for m in initializes] == ["session #1", "session #2", "session #3"]
    assert token not in caplog.text
    assert run_tokens.employee_of(token) == 1  # not revoked
