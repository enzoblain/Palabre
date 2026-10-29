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
