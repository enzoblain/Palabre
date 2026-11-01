"""Runs under AGENT_USER (#104): sudo with an explicit environment, no secret in argv."""

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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
    claims = []

    async def claim(paths, user):
        claims.append((paths, user))

    monkeypatch.setattr(runner, "_claim", claim)  # needs root and the image's sudo rule
    return claims


def spec(tmp_path):
    return RunSpec(
        author_name="Mehdi", system_prompt="sys", prompt="do it", cwd=tmp_path, employee_id=1,
        mcp_headers={"Authorization": HEADER}, mcp_tools=["a"], claude_tools=["Read"],
        model="m", oauth_token=TOKEN,
    )  # fmt: skip


def test_env_is_explicit_and_the_agents(as_agent):
    env = runner._env("Mehdi", "run-token", Path("/data/projects/1/desks/employee-3"))
    assert env["HOME"] == "/root"  # the agent account's, not the backend's
    assert "/home/palabre" not in env["PATH"]
    # The agent holds its run token, never the account's: the Anthropic proxy adds the real one
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "run-token" and TOKEN not in env.values()
    assert env["ANTHROPIC_BASE_URL"] == runner.settings.anthropic_proxy_url
    # Outbound traffic goes through the allowlisting proxy; the MCP server on loopback is not proxied
    assert env["HTTPS_PROXY"] == f"http://127.0.0.1:{runner.settings.egress_proxy_port}"
    assert "127.0.0.1" in env["NO_PROXY"]
    assert set(env) <= set(runner.ENV_ALLOWLIST) | {
        "LOGNAME", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "MCP_TOOL_TIMEOUT", "GOPATH", "GOMODCACHE", "CGO_ENABLED",
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
        "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0",
    }  # fmt: skip
    # safe.directory is this run's clone only: git does not glob it
    assert env["GIT_CONFIG_COUNT"] == "1" and env["GIT_CONFIG_KEY_0"] == "safe.directory"
    assert env["GIT_CONFIG_VALUE_0"] == "/data/projects/1/desks/employee-3"
    assert "ghp_secret" not in "".join(env.values()) and "dbpass" not in "".join(env.values())


def test_unknown_agent_user_is_refused(as_agent, monkeypatch):
    monkeypatch.setattr(settings, "agent_user", "no-such-user-xyz")
    with pytest.raises(ClaudeRunError, match="does not exist"):
        runner._env("Mehdi", "run-token", Path("/data/projects/1/desks/employee-3"))


def test_command_goes_through_sudo_without_secrets_in_argv(as_agent, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: f"/home/palabre/.local/bin/{name}")
    env = runner._env("Mehdi", "run-token", Path("/data/projects/1/desks/employee-3"))
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

        async def communicate(self, input=None):
            return b'{"session_id": "s", "result": "ok"}', b""

    async def fake_exec(*argv, **kw):
        seen.update(argv=argv, **kw)
        return Proc()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    result = await runner.run_claude(spec(tmp_path))
    assert result.session_id == "s"
    assert seen["argv"][0] == "sudo" and seen["start_new_session"] is True
    assert TOKEN not in " ".join(seen["argv"]) and HEADER not in " ".join(seen["argv"])
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] != TOKEN and TOKEN not in seen["env"].values()
    assert "DATABASE_URL" not in seen["env"] and "GITHUB_TOKEN" not in seen["env"]
    assert list((tmp_path / "run").iterdir()) == []


async def test_timeout_kills_the_group_through_sudo(as_agent, monkeypatch, tmp_path):
    calls = []

    class Proc:
        pid = 4242
        returncode = None

        async def communicate(self, input=None):
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

        async def communicate(self, input=None):
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
    assert "DATABASE_URL" not in seen["env"] and TOKEN not in seen["env"].values()
    assert seen["path"].parent == tmp_path / "run" and seen["mode"] == 0o640  # #104 dir, #108 rights
    headers = seen["config"]["mcpServers"][runner.SERVER_NAME]["headers"]
    assert seen["token"] and headers["Authorization"] != HEADER  # per-run token, not the caller's header
    assert seen["token"] not in " ".join(seen["argv"])
    assert seen["employee"] == 7 and seen["deleted_on_use"]  # #108
    assert run_tokens.employee_of(seen["token"]) is None  # revoked at the end of the run
    assert not seen["path"].exists()


def test_agent_env_lets_git_work_in_a_foreign_owned_clone(as_agent, tmp_path):
    clone = tmp_path / "desk"
    clone.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=clone, check=True)
    env = runner._env("Mehdi", "run-token", clone)
    # The agent account's HOME is not ours to read here
    env = {**env, "HOME": str(tmp_path), "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1", "XDG_CONFIG_HOME": str(tmp_path),
           "GIT_CONFIG_NOSYSTEM": "1"}  # the runner image trusts every directory system-wide

    def status(env):
        return subprocess.run(["git", "status"], cwd=clone, env=env, capture_output=True, text=True)

    refused = status({k: v for k, v in env.items() if not k.startswith(("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY", "GIT_CONFIG_VALUE"))})
    assert refused.returncode != 0 and "dubious ownership" in refused.stderr
    assert status(env).returncode == 0


def test_run_config_dir_is_throwaway_and_sessions_stay_private(as_agent, monkeypatch, tmp_path):
    from app import claude_store

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "store"))
    sid = "11111111-2222-3333-4444-555555555555"
    for emp in (1, 2):
        d = claude_store.employee_store(emp) / "projects" / "-data-p"
        d.mkdir(parents=True)
        (d / f"{sid}.jsonl").write_text(f"employee {emp}")
    (claude_store.employee_store(1) / "settings.json").write_text("{}")

    run_dir = claude_store.prepare_run_dir(2, sid)
    assert run_dir.parent == tmp_path / "run"
    assert env_dir(run_dir) == str(run_dir)
    # Only employee 2's session comes in: nothing of employee 1's, no settings
    assert [p.read_text() for p in run_dir.rglob("*.jsonl")] == ["employee 2"]
    assert not list(run_dir.rglob("settings.json"))

    # The run plants a hook, a symlink to a secret and a new session
    (run_dir / "settings.json").write_text('{"hooks": {}}')
    secret = tmp_path / "secret"
    secret.write_text("db-password")
    (run_dir / "projects" / "-data-p" / "leak.jsonl").symlink_to(secret)
    (run_dir / "projects" / "-data-p" / f"{sid}.jsonl").write_text("employee 2, updated")
    claude_store.collect_run_dir(2, run_dir)

    store = claude_store.employee_store(2)
    assert not run_dir.exists()
    assert (store / "projects" / "-data-p" / f"{sid}.jsonl").read_text() == "employee 2, updated"
    assert not (store / "settings.json").exists()
    assert not (store / "projects" / "-data-p" / "leak.jsonl").exists()
    assert (claude_store.employee_store(1) / "projects" / "-data-p" / f"{sid}.jsonl").read_text() == "employee 1"


def env_dir(path):
    return runner._env("Mehdi", "run-token", Path("/x"), path)["CLAUDE_CONFIG_DIR"]


def test_resume_id_cannot_escape_the_store(as_agent, monkeypatch, tmp_path):
    from app import claude_store

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "store"))
    (tmp_path / "store" / "employee-1" / "projects" / "p").mkdir(parents=True)
    run_dir = claude_store.prepare_run_dir(1, "../../employee-1")
    assert not (run_dir / "projects").exists()


def test_file_swapped_for_a_symlink_after_the_scan_is_not_followed(as_agent, monkeypatch, tmp_path):
    from app import claude_store

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "store"))
    secret = tmp_path / "secret"
    secret.write_text("db-password")
    run_dir = claude_store.prepare_run_dir(1, None)
    project = run_dir / "projects" / "p"
    project.mkdir(parents=True)
    (project / "s.jsonl").write_text("mine")
    (project / "sub").mkdir()
    real_listdir = os.listdir

    def swapping(fd):
        names = real_listdir(fd)
        # Between the listing and the open: a file and a directory become symlinks
        if "s.jsonl" in names:
            (project / "s.jsonl").unlink()
            (project / "s.jsonl").symlink_to(secret)
            (project / "sub").rmdir()
            (project / "sub").symlink_to(tmp_path)
        return names

    monkeypatch.setattr(claude_store.os, "listdir", swapping)
    claude_store.collect_run_dir(1, run_dir)
    monkeypatch.undo()
    copied = [p for p in (tmp_path / "store").rglob("*") if p.is_file()]
    assert copied == []


def test_run_dir_keeps_setgid(as_agent, tmp_path):
    from app import claude_store

    run_dir = claude_store.prepare_run_dir(1, None)
    assert run_dir.stat().st_mode & 0o7777 == 0o2770


def test_failing_copy_does_not_lose_the_result(as_agent, monkeypatch, tmp_path):
    from app import claude_store

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "store"))
    run_dir = claude_store.prepare_run_dir(1, None)

    def full_disk(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(claude_store, "_copy_tree", full_disk)
    assert claude_store.collect_run_dir(1, run_dir) is True  # logged, run dir still deleted
    assert not run_dir.exists()


def test_copy_reads_at_most_the_checked_size(as_agent, monkeypatch, tmp_path):
    from app import claude_store

    src = tmp_path / "src"
    src.mkdir()
    (src / "s.jsonl").write_text("x" * 100)
    monkeypatch.setattr(claude_store, "MAX_FILE_BYTES", 10)
    claude_store._copy_tree(src, tmp_path / "dst", file_mode=0o600, dir_mode=0o700)
    assert not (tmp_path / "dst" / "s.jsonl").exists()  # over the cap: skipped


# One system user per live run (#152)


def test_pool_users_are_numbered_after_agent_user(monkeypatch):
    from app import agent_pool

    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 2)
    assert agent_pool.users() == ["agent1", "agent2", "agent"]


@pytest.fixture
def kills(monkeypatch):
    from app import agent_pool

    killed = []

    async def fake(user):
        killed.append(user)
        return True

    monkeypatch.setattr(agent_pool, "kill_all", fake)
    return killed


def test_live_runs_never_share_a_user(monkeypatch, kills):
    from app import agent_pool

    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 2)
    agent_pool.reset()

    async def scenario():
        order = []
        release = asyncio.Event()

        async def run(name):
            async with agent_pool.lease() as user:
                order.append((name, user))
                await release.wait()

        tasks = [asyncio.create_task(run(n)) for n in "abc"]
        await asyncio.sleep(0.05)
        # The third run waits for a free account instead of sharing one
        assert len(order) == 2 and order[0][1] != order[1][1]
        release.set()
        await asyncio.gather(*tasks)
        assert len(order) == 3

    asyncio.run(scenario())
    agent_pool.reset()


def test_cancelled_waiter_does_not_leak_a_user(monkeypatch, kills):
    from app import agent_pool

    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 1)
    agent_pool.reset()

    async def scenario():
        async with agent_pool.lease() as first:
            waiter = asyncio.create_task(agent_pool.lease().__aenter__())
            await asyncio.sleep(0.01)
            waiter.cancel()
        async with agent_pool.lease() as again:
            assert again == first

    asyncio.run(scenario())
    agent_pool.reset()


def test_no_pool_keeps_the_single_agent_user(monkeypatch):
    from app import agent_pool

    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 0)

    async def scenario():
        async with agent_pool.lease() as a, agent_pool.lease() as b:
            assert a == b == "agent"

    asyncio.run(scenario())


def test_command_runs_as_the_leased_user(as_agent, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/home/palabre/.local/bin/claude")
    cmd = runner._command(["claude", "-p"], {"A": "b"}, "agent3")
    assert cmd[:4] == ["sudo", "-n", "-u", "agent3"]


def test_mcp_config_of_a_pool_user_belongs_to_its_group(as_agent, monkeypatch):
    calls = []
    monkeypatch.setattr(shutil, "chown", lambda path, user=None, group=None: calls.append((Path(path).name[:4], group)))
    path = runner._write_mcp_config({"Authorization": HEADER}, "agent3")
    assert path.stat().st_mode & 0o777 == 0o640
    assert calls == [("mcp-", "agent3")]  # group agent3 only: other runs' users are not in it


@pytest.mark.skipif(os.geteuid() != 0 or shutil.which("setpriv") is None, reason="needs root and setpriv")
def test_other_uid_cannot_read_environ_of_a_live_run(tmp_path):
    secret = "sk-ant-oat-lead-secret"
    proc = subprocess.Popen(
        ["setpriv", "--reuid=65001", "--regid=65001", "--clear-groups", "sleep", "30"],
        env={"CLAUDE_CODE_OAUTH_TOKEN": secret}, stdin=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        out = subprocess.run(
            ["setpriv", "--reuid=65002", "--regid=65002", "--clear-groups", "cat", f"/proc/{proc.pid}/environ"],
            capture_output=True, text=True,
        )  # fmt: skip
        assert out.returncode != 0 and secret not in out.stdout
    finally:
        proc.kill()
        proc.wait()


def test_user_is_emptied_before_it_returns_to_the_pool(monkeypatch, kills):
    from app import agent_pool

    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 1)
    agent_pool.reset()

    async def scenario():
        async with agent_pool.lease() as user:
            assert kills == []
        assert kills == [user]

    asyncio.run(scenario())
    agent_pool.reset()


def test_user_whose_processes_cannot_be_killed_is_not_reused(monkeypatch, kills):
    from app import agent_pool

    async def failing(user):
        return False

    monkeypatch.setattr(agent_pool, "kill_all", failing)
    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 2)
    agent_pool.reset()

    async def scenario():
        async with agent_pool.lease() as first:
            pass
        async with agent_pool.lease() as second:
            assert second != first

    asyncio.run(scenario())
    agent_pool.reset()


def test_kill_all_runs_the_sudo_kill_of_the_whole_uid(monkeypatch):
    from app import agent_pool

    seen = {}

    class Proc:
        returncode = 1

        async def communicate(self, input=None):
            return b"", b"kill: sending signal to -1 failed: No such process"

    async def fake_exec(*args, **kw):
        seen["args"] = args
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert asyncio.run(agent_pool.kill_all("agent3")) is True
    assert seen["args"] == ("sudo", "-n", "-u", "agent3", "/usr/bin/kill", "-KILL", "--", "-1")


def test_wakeup_of_a_cancelled_waiter_goes_to_the_next(monkeypatch, kills):
    from app import agent_pool

    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 1)
    agent_pool.reset()

    async def scenario():
        got = []

        async def want(name):
            async with agent_pool.lease() as user:
                got.append(name)

        cm = agent_pool.lease()
        await cm.__aenter__()
        first = asyncio.create_task(want("a"))
        second = asyncio.create_task(want("b"))
        await asyncio.sleep(0.01)
        await cm.__aexit__(None, None, None)  # wakes "a"...
        first.cancel()  # ...which is cancelled before it runs
        await asyncio.wait_for(second, 1)
        assert "b" in got

    asyncio.run(scenario())
    agent_pool.reset()


def test_pool_user_gets_a_fresh_home_in_its_run_dir(as_agent, monkeypatch, tmp_path):
    from app import claude_store

    monkeypatch.setattr(settings, "agent_user", "root")
    monkeypatch.setattr(shutil, "chown", lambda *a, **k: None)
    pw = runner.pwd.getpwnam("root")
    monkeypatch.setattr(runner, "_agent_account", lambda user: pw)
    run_dir = claude_store.prepare_run_dir(1, None, "agent3")
    assert (run_dir / "home").is_dir()
    env = runner._env("Mehdi", "run-token", tmp_path, run_dir, "agent3")
    assert env["HOME"] == str(run_dir / "home")
    # The legacy single user keeps its persistent home
    assert runner._env("Mehdi", "run-token", tmp_path, run_dir, "root")["HOME"] == "/root"


# Follow-ups of #152


def test_pool_user_gets_a_tmpdir_in_its_run_dir(as_agent, monkeypatch, tmp_path):
    from app import claude_store

    monkeypatch.setattr(shutil, "chown", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_agent_account", lambda user: runner.pwd.getpwnam("root"))
    run_dir = claude_store.prepare_run_dir(1, None, "agent3")
    assert (run_dir / "tmp").is_dir()
    assert runner._env("Mehdi", "run-token", tmp_path, run_dir, "agent3")["TMPDIR"] == str(run_dir / "tmp")
    # The legacy single user shares its uid between runs: no per-run tmp
    assert "TMPDIR" not in runner._env("Mehdi", "run-token", tmp_path, run_dir, "root")


async def test_uid_is_killed_before_the_run_dir_is_collected(as_agent, monkeypatch, tmp_path):
    from app import agent_pool, claude_store

    order = []

    class Proc:
        returncode = 0
        pid = 1

        async def communicate(self, input=None):
            return b'{"session_id": "s", "result": "ok"}', b""

    async def fake_exec(*argv, **kw):
        return Proc()

    async def fake_kill(user):
        order.append(("kill", user))
        return True

    async def fake_collect(employee_id, run_dir, user=None):
        order.append(("collect", user))

    monkeypatch.setattr(shutil, "chown", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_agent_account", lambda user: runner.pwd.getpwnam("root"))
    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(agent_pool, "kill_all", fake_kill)
    monkeypatch.setattr(claude_store, "collect", fake_collect)
    await runner._run_claude(spec(tmp_path), "tok", "agent3")
    assert order == [("kill", "agent3"), ("collect", "agent3")]


def test_pool_shrinks_to_the_accounts_that_exist(monkeypatch, caplog):
    from app import agent_pool

    present = {"agent1", "agent2", "agent4"}

    def getpwnam(name):
        if name not in present:
            raise KeyError(name)

    monkeypatch.setattr(agent_pool.pwd, "getpwnam", getpwnam)
    monkeypatch.setattr(agent_pool.grp, "getgrnam", getpwnam)
    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 4)
    agent_pool.check()
    assert settings.agent_pool_size == 2
    assert "agent3 (user and group) does not exist" in caplog.text
    agent_pool.reset()


def test_pool_without_any_account_refuses_to_start(monkeypatch):
    from app import agent_pool

    def missing(name):
        raise KeyError(name)

    monkeypatch.setattr(agent_pool.pwd, "getpwnam", missing)
    monkeypatch.setattr(agent_pool.grp, "getgrnam", missing)
    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 8)
    with pytest.raises(RuntimeError, match="shared uid"):
        agent_pool.check()
    assert settings.agent_pool_size == 8  # not silently turned into "no pool"


def test_pool_with_a_user_but_no_group_is_shrunk(monkeypatch):
    from app import agent_pool

    monkeypatch.setattr(agent_pool.pwd, "getpwnam", lambda name: None)

    def group(name):
        if name != "agent1":
            raise KeyError(name)

    monkeypatch.setattr(agent_pool.grp, "getgrnam", group)
    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 3)
    agent_pool.check()
    assert settings.agent_pool_size == 1
    agent_pool.reset()


@pytest.fixture
def pooled(monkeypatch):
    """A run on pool account agent3; records the kill and the release order."""
    events = []

    @contextlib.asynccontextmanager
    async def lease():
        yield "agent3"

    async def kill_all(user):
        events.append("kill")
        return kill_ok[0]

    kill_ok = [True]
    monkeypatch.setattr(runner.shutil, "chown", lambda *a, **k: None)  # agent3 does not exist here
    monkeypatch.setattr(
        runner, "_agent_account", lambda user: SimpleNamespace(pw_name=user, pw_dir=f"/home/{user}")
    )
    monkeypatch.setattr(runner.claude_store, "prepare_run_dir", lambda *a: None)
    monkeypatch.setattr(runner.agent_pool, "lease", lease)
    monkeypatch.setattr(runner.agent_pool, "kill_all", kill_all)
    return events, kill_ok


def _track_quarantine(monkeypatch):
    quarantined = set()
    monkeypatch.setattr(runner.agent_pool, "quarantine", quarantined.add)
    monkeypatch.setattr(runner.agent_pool, "unquarantine", quarantined.discard)
    return quarantined


def _fake_proc(monkeypatch, events):
    class Proc:
        returncode = 0

        async def communicate(self, input=None):
            return b'{"session_id": "s", "result": "ok"}', b""

    async def fake_exec(*argv, **kw):
        events.append("run")
        return Proc()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)


async def test_run_claims_its_clone_then_releases_it_after_the_kill(as_agent, pooled, monkeypatch, tmp_path):
    events, _ = pooled

    async def claim(paths, user):
        events.append(f"claim:{user}")

    monkeypatch.setattr(runner, "_claim", claim)
    _fake_proc(monkeypatch, events)
    await runner.run_claude(replace(spec(tmp_path), employee_id=7))
    assert events == ["claim:agent3", "run", "kill", "claim:palabre"]


async def test_clone_is_not_released_if_the_account_cannot_be_killed(as_agent, pooled, monkeypatch, tmp_path):
    events, kill_ok = pooled
    kill_ok[0] = False

    async def claim(paths, user):
        events.append(f"claim:{user}")

    monkeypatch.setattr(runner, "_claim", claim)
    _fake_proc(monkeypatch, events)
    await runner.run_claude(replace(spec(tmp_path), employee_id=7))
    assert "claim:palabre" not in events


async def test_account_stays_out_of_the_pool_if_the_clone_cannot_be_taken_back(as_agent, pooled, monkeypatch, tmp_path):
    events, _ = pooled

    async def claim(paths, user):
        if user == "palabre":
            raise runner.ClaudeRunError("boom")

    quarantined = _track_quarantine(monkeypatch)
    monkeypatch.setattr(runner, "_claim", claim)
    _fake_proc(monkeypatch, events)
    await runner.run_claude(replace(spec(tmp_path), employee_id=7))
    assert quarantined == {"agent3"}


async def test_account_is_lifted_from_quarantine_once_the_clone_is_back(as_agent, pooled, monkeypatch, tmp_path):
    events, _ = pooled

    async def claim(paths, user):
        pass

    quarantined = _track_quarantine(monkeypatch)
    monkeypatch.setattr(runner, "_claim", claim)
    _fake_proc(monkeypatch, events)
    await runner.run_claude(replace(spec(tmp_path), employee_id=7))
    assert quarantined == set()


async def test_account_stays_quarantined_if_the_hand_back_is_cancelled(as_agent, pooled, monkeypatch, tmp_path):
    events, _ = pooled

    async def claim(paths, user):
        if user == "palabre":
            raise asyncio.CancelledError

    quarantined = _track_quarantine(monkeypatch)
    monkeypatch.setattr(runner, "_claim", claim)
    _fake_proc(monkeypatch, events)
    with pytest.raises(asyncio.CancelledError):
        await runner.run_claude(replace(spec(tmp_path), employee_id=7))
    assert quarantined == {"agent3"}


async def test_clone_is_taken_back_even_if_collecting_the_session_fails(as_agent, pooled, monkeypatch, tmp_path):
    events, _ = pooled

    async def claim(paths, user):
        events.append(f"claim:{user}")

    async def collect(*a):
        raise OSError("disk full")

    monkeypatch.setattr(runner, "_claim", claim)
    monkeypatch.setattr(runner.claude_store, "prepare_run_dir", lambda *a: tmp_path)
    monkeypatch.setattr(runner.claude_store, "collect", collect)
    _fake_proc(monkeypatch, events)
    with pytest.raises(OSError):
        await runner.run_claude(replace(spec(tmp_path), employee_id=7))
    assert events[-1] == "claim:palabre"


async def test_unkillable_account_is_quarantined(as_agent, pooled, monkeypatch, tmp_path):
    events, kill_ok = pooled
    kill_ok[0] = False
    quarantined = _track_quarantine(monkeypatch)

    async def claim(paths, user):
        pass

    monkeypatch.setattr(runner, "_claim", claim)
    _fake_proc(monkeypatch, events)
    await runner.run_claude(replace(spec(tmp_path), employee_id=7))
    assert quarantined == {"agent3"}


async def test_lease_does_not_release_a_quarantined_account(monkeypatch):
    from app import agent_pool

    agent_pool.reset()
    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 1)

    async def kill_all(user):
        return True

    monkeypatch.setattr(agent_pool, "kill_all", kill_all)
    async with agent_pool.lease() as user:
        agent_pool.quarantine(user)
    assert user not in agent_pool._pool.free
    agent_pool.reset()


async def test_clone_is_released_when_the_run_times_out(as_agent, pooled, monkeypatch, tmp_path):
    events, _ = pooled
    paths_seen = []

    async def claim(paths, user):
        events.append(f"claim:{user}")
        paths_seen.append(paths)

    class Proc:
        async def communicate(self, input=None):
            raise TimeoutError

        async def wait(self):
            return 0

    async def fake_exec(*argv, **kw):
        return Proc()

    async def terminate(proc, user=None):
        events.append("terminate")

    monkeypatch.setattr(runner, "_claim", claim)
    monkeypatch.setattr(runner, "_terminate", terminate)
    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(runner.asyncio, "wait_for", lambda coro, t: coro)
    with pytest.raises(runner.ClaudeRunError):
        await runner.run_claude(replace(spec(tmp_path), employee_id=7))
    assert events[-2:] == ["kill", "claim:palabre"]
    assert paths_seen[0] == [tmp_path, settings.toolchains_dir / "gopath" / "employee-7"]


def test_go_cache_is_per_employee(as_agent):
    a = runner._env("Mehdi", "run-token", Path("/x"), None, None, 1)
    b = runner._env("Mehdi", "run-token", Path("/x"), None, None, 2)
    assert a["GOPATH"] != b["GOPATH"] and a["GOMODCACHE"].startswith(a["GOPATH"])


async def test_claim_never_chmods_an_existing_directory(monkeypatch, tmp_path):
    chmods = []
    monkeypatch.setattr(Path, "chmod", lambda self, mode: chmods.append((self.name, mode)))

    class Proc:
        returncode = 0

        async def communicate(self, input=None):
            return b"", b""

    async def fake_exec(*a, **k):
        return Proc()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    existing = tmp_path / "existing"
    existing.mkdir()
    # A claim, then a release, on a directory that exists: the claim script takes it over, no chmod here
    await runner._claim([existing], "agent1")
    await runner._claim([existing], "palabre")
    assert chmods == []
    # A directory just created is closed to the work group from the start
    await runner._claim([tmp_path / "fresh"], "agent1")
    assert chmods == [("fresh", 0o700)]


async def test_prompts_stay_out_of_argv(as_agent, monkeypatch, tmp_path):
    seen = {}

    class Proc:
        returncode = 0
        pid = 1

        async def communicate(self, input=None):
            seen["stdin"] = input
            seen["system_prompt"] = Path(seen["argv"][seen["argv"].index("--append-system-prompt-file") + 1]).read_text()
            return b'{"session_id": "s", "result": "ok"}', b""

    async def fake_exec(*argv, **kw):
        seen.update(argv=list(argv), **kw)
        return Proc()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    run_spec = replace(spec(tmp_path), prompt="SECRET-USER-PROMPT", system_prompt="SECRET-SYSTEM-PROMPT")
    await runner.run_claude(run_spec)
    assert "SECRET" not in " ".join(seen["argv"])
    assert seen["stdin"] == b"SECRET-USER-PROMPT"
    assert seen["system_prompt"] == "SECRET-SYSTEM-PROMPT"
    assert list((tmp_path / "run").iterdir()) == []


def test_run_without_employee_keeps_nothing_and_is_deleted(as_agent, monkeypatch, tmp_path):
    from app import claude_store

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "store"))
    run_dir = claude_store.prepare_run_dir(0, None)
    session = run_dir / "projects" / "p" / "s.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text("{}")

    assert claude_store.collect_run_dir(None, run_dir) is True
    assert not run_dir.exists()
    assert not (tmp_path / "store").exists()
