"""A run's MCP token only works while the run lives."""

import pytest

from app import runner
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


async def test_extra_sessions_are_logged_not_alerted_nor_refused(monkeypatch, caplog):
    posted = []

    async def fake_resolve(token, conversation, task):
        return auth.Caller(1, 1, 1, 1, None, frozenset()) if run_tokens.employee_of(token) else None

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"mcp-session-id", b"s1")]})

    monkeypatch.setattr(auth, "resolve_caller", fake_resolve)
    monkeypatch.setattr(auth, "SessionLocal", lambda: posted.append(1))  # any chat post would open a session
    app = auth.AgentAuthMiddleware(inner)
    token = run_tokens.issue(1)

    with caplog.at_level("INFO", logger=auth.log.name):
        assert await _call(app, token) == 200
        assert await _call(app, token) == 200  # second initialize: allowed
        assert await _call(app, token) == 200  # third
        assert await _call(app, token, "s1") == 200
        assert await _call(app, token, "other") == 200
    assert posted == []
    initializes = [r.getMessage() for r in caplog.records if "MCP initialize" in r.getMessage()]
    assert [m.split(":")[1].split(" of")[0].strip() for m in initializes] == ["session #1", "session #2", "session #3"]
    assert all(r.levelname == "INFO" for r in caplog.records)
    assert token not in caplog.text
    run_tokens.revoke(token)
    assert await _call(app, token, "s1") == 401  # the run is over: the token is dead


async def test_headers_must_match_the_scope_recorded_with_the_token(caplog):
    token = run_tokens.issue(1, task_id=5)
    assert run_tokens.scope_of(token) == (5, None)
    with caplog.at_level("WARNING", logger=auth.log.name):
        assert await auth.resolve_caller(token, "", "6") is None  # other task
        assert await auth.resolve_caller(token, "3", "") is None  # conversation headers on a task token
        assert await auth.resolve_caller(token, "3", "5") is None  # extra header
        assert await auth.resolve_caller(token, "", "") is None  # no header
    assert caplog.text.count("do not match the scope") == 4
    assert token not in caplog.text
    run_tokens.revoke(token)
    assert run_tokens.scope_of(token) == (None, None)


async def test_unscoped_token_refuses_any_scope_header():
    token = run_tokens.issue(1)
    assert await auth.resolve_caller(token, "1", "") is None
    assert await auth.resolve_caller(token, "", "1") is None
    run_tokens.revoke(token)


@pytest.fixture(autouse=True)
def clean_tokens():
    yield
    for d in (run_tokens._active, run_tokens._scopes, run_tokens._initializes):
        d.clear()


def test_matching_headers_are_accepted():
    task_token = run_tokens.issue(1, task_id=7)
    assert run_tokens.scope_matches(task_token, "", "7")
    assert not run_tokens.scope_matches(task_token, "", "07")
    conversation_token = run_tokens.issue(1, conversation_id=3)
    assert run_tokens.scope_matches(conversation_token, "3", "")
    assert not run_tokens.scope_matches(conversation_token, "", "3")  # headers swapped


async def test_matching_headers_reach_the_database_lookup(monkeypatch):
    class FakeTask:
        project_id, assignee_id, room_id, conversation_id, id = 1, 1, 2, 3, 7

    class FakeEmployee:
        id, project_id, permissions = 1, 1, {}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, model, pk):
            return FakeEmployee() if model is auth.Employee else FakeTask()

    monkeypatch.setattr(auth, "SessionLocal", FakeSession)
    monkeypatch.setattr(auth, "mcp_tools_for", lambda permissions, task_run: frozenset({"x"}))
    token = run_tokens.issue(1, task_id=7)
    caller = await auth.resolve_caller(token, "", "7")
    assert caller is not None and caller.task_id == 7 and caller.employee_id == 1


@pytest.mark.parametrize(
    "headers, scope",
    [({"X-Palabre-Task": "7"}, (7, None)), ({"X-Palabre-Conversation": "3"}, (None, 3))],
)
async def test_run_claude_records_the_scope_of_the_headers(monkeypatch, tmp_path, headers, scope):
    seen = {}

    async def fake_run(spec, token, user=""):
        seen["scope"] = run_tokens.scope_of(token)
        seen["token"] = token

    monkeypatch.setattr(runner, "_run_claude", fake_run)
    spec = runner.RunSpec(
        author_name="Mehdi", system_prompt="s", prompt="p", cwd=tmp_path, employee_id=1,
        mcp_headers=headers, mcp_tools=[], claude_tools=[], model="m", oauth_token="t",
    )  # fmt: skip
    await runner.run_claude(spec)
    assert seen["scope"] == scope
    assert run_tokens.scope_of(seen["token"]) == (None, None)  # revoked afterwards


async def test_non_numeric_scope_header_is_logged(monkeypatch, tmp_path, caplog):
    async def fake_run(spec, token, user=""):
        assert run_tokens.scope_of(token) == (None, None)

    monkeypatch.setattr(runner, "_run_claude", fake_run)
    spec = runner.RunSpec(
        author_name="Mehdi", system_prompt="s", prompt="p", cwd=tmp_path, employee_id=1,
        mcp_headers={"X-Palabre-Task": "x"}, mcp_tools=[], claude_tools=[], model="m", oauth_token="t",
    )  # fmt: skip
    await runner.run_claude(spec)
    assert "non-numeric" in caplog.text
