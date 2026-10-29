"""Runs under AGENT_USER (#104): sudo with an explicit environment, no secret in argv."""

import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from app import runner
from app.config import settings
from app.runner import ClaudeRunError, RunSpec

TOKEN = "sk-ant-oat-secret"
HEADER = "mcp-secret-header"


@pytest.fixture
def as_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "agent_user", "root")  # any account that exists here
    monkeypatch.setattr(settings, "agent_run_dir", tmp_path / "run")
    monkeypatch.setattr(settings, "runtime_dir", tmp_path / "runtime")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:dbpass@h/db")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKENS", TOKEN + "|other")
    monkeypatch.setenv("PATH", "/home/palabre/.local/bin:/usr/bin")
    monkeypatch.setenv("HOME", "/home/palabre")


def spec(tmp_path):
    return RunSpec(
        author_name="Mehdi", system_prompt="sys", prompt="do it", cwd=tmp_path, employee_id=1,
        mcp_headers={"Authorization": HEADER}, mcp_tools=["a"], claude_tools=["Read"],
        model="m", oauth_token=TOKEN,
    )  # fmt: skip


def test_env_is_explicit_and_the_agents(as_agent):
    env = runner._env("Mehdi", TOKEN)
    assert env["HOME"] == "/root"  # the agent account's, not the backend's
    assert "/home/palabre" not in env["PATH"]
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
    assert set(env) <= set(runner.ENV_ALLOWLIST) | {
        "LOGNAME", "CLAUDE_CODE_OAUTH_TOKEN", "MCP_TOOL_TIMEOUT", "GOPATH", "GOMODCACHE", "CGO_ENABLED",
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
    }  # fmt: skip
    assert "ghp_secret" not in "".join(env.values()) and "dbpass" not in "".join(env.values())


def test_unknown_agent_user_is_refused(as_agent, monkeypatch):
    monkeypatch.setattr(settings, "agent_user", "no-such-user-xyz")
    with pytest.raises(ClaudeRunError, match="does not exist"):
        runner._env("Mehdi", TOKEN)


def test_command_goes_through_sudo_without_secrets_in_argv(as_agent, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/home/palabre/.local/bin/{name}")
    env = runner._env("Mehdi", TOKEN)
    cmd = runner._command(["claude", "-p", "do it"], env)
    assert cmd[:5] == ["sudo", "-n", "-u", "root", cmd[4]] and cmd[4].startswith("--preserve-env=")
    assert cmd[5:] == ["--", "/home/palabre/.local/bin/claude", "-p", "do it"]
    assert TOKEN not in " ".join(cmd)
    names = cmd[4].removeprefix("--preserve-env=").split(",")
    assert set(names) == set(env)  # exactly the explicit variables


def test_without_agent_user_nothing_changes(monkeypatch):
    monkeypatch.setattr(settings, "agent_user", "")
    assert runner._command(["claude", "-p"], {"A": "b"}) == ["claude", "-p"]


def test_mcp_config_readable_by_the_group_only_when_agent_user(as_agent, tmp_path):
    path = runner._write_mcp_config({"Authorization": HEADER})
    assert path.parent == tmp_path / "run" and path.stat().st_mode & 0o777 == 0o640
    assert path.parent.stat().st_mode & 0o777 == 0o711
    assert not (tmp_path / "runtime").exists()


async def test_run_launches_sudo_and_cleans_up(as_agent, monkeypatch, tmp_path):
    seen = {}

    class Proc:
        returncode = 0
        pid = 1

        async def communicate(self):
            return b'{"session_id": "s", "result": "ok"}', b""

    async def fake_exec(*argv, **kw):
        seen.update(argv=argv, **kw)
        return Proc()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    result = await runner.run_claude(spec(tmp_path))
    assert result.session_id == "s"
    assert seen["argv"][0] == "sudo" and seen["start_new_session"] is True
    assert TOKEN not in " ".join(seen["argv"]) and HEADER not in " ".join(seen["argv"])
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
    assert "DATABASE_URL" not in seen["env"] and "GITHUB_TOKEN" not in seen["env"]
    assert list((tmp_path / "run").iterdir()) == []


async def test_timeout_kills_the_group_through_sudo(as_agent, monkeypatch, tmp_path):
    calls = []

    class Proc:
        pid = 4242
        returncode = None

        async def communicate(self):
            await asyncio.sleep(10)

        async def wait(self):
            return 0

    class Killer:
        async def wait(self):
            return 0

    async def fake_exec(*argv, **kw):
        calls.append(argv)
        return Proc() if len(calls) == 1 else Killer()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(settings, "agent_timeout_s", 0.05)
    with pytest.raises(ClaudeRunError, match="Timed out"):
        await runner.run_claude(spec(tmp_path))
    assert calls[1][:5] == ("sudo", "-n", "-u", "root", "/usr/bin/kill")
    assert calls[1][-3:] == ("-KILL", "--", "-4242")


async def test_sudo_run_uses_a_per_run_token_in_the_agent_dir_and_revokes_it(as_agent, monkeypatch, tmp_path):
    """#104 and #108 together: sudo + explicit env, and a per-run token in a config the agent can read."""
    from app.mcp_server import run_tokens

    seen = {}

    class Proc:
        returncode = 0
        pid = 1

        async def communicate(self):
            # While the run lives: the config sits in the agent dir with the #108 rights
            path = Path(seen["argv"][seen["argv"].index("--mcp-config") + 1])
            seen["path"], seen["mode"] = path, path.stat().st_mode & 0o777
            seen["config"] = json.loads(path.read_text())
            token = seen["config"]["mcpServers"][runner.SERVER_NAME]["headers"]["Authorization"].removeprefix("Bearer ")
            seen["token"], seen["employee"] = token, run_tokens.employee_of(token)  # first use deletes the file
            seen["deleted_on_use"] = not path.exists()
            return b'{"session_id": "s", "result": "ok"}', b""

    async def fake_exec(*argv, **kw):
        seen.update(argv=argv, **kw)
        return Proc()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    run_spec = replace(spec(tmp_path), employee_id=7)
    await runner.run_claude(run_spec)

    assert seen["argv"][:4] == ("sudo", "-n", "-u", "root")  # #104
    assert "DATABASE_URL" not in seen["env"] and seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
    assert seen["path"].parent == tmp_path / "run" and seen["mode"] == 0o640  # #104 dir, #108 rights
    headers = seen["config"]["mcpServers"][runner.SERVER_NAME]["headers"]
    assert seen["token"] and headers["Authorization"] != HEADER  # per-run token, not the caller's header
    assert seen["token"] not in " ".join(seen["argv"])
    assert seen["employee"] == 7 and seen["deleted_on_use"]  # #108
    assert run_tokens.employee_of(seen["token"]) is None  # revoked at the end of the run
    assert not seen["path"].exists()
