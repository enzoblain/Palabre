"""Runs under AGENT_USER (#104): sudo with an explicit environment, no secret in argv."""

import asyncio
import shutil

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
