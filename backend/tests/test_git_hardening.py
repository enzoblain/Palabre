"""github.git must not run agent-planted hooks or fsmonitor, and only network commands get the token."""

import asyncio
import subprocess

import pytest

from app import github
from app.config import settings


def _init_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)  # fmt: skip


def _plant(path, marker):
    hooks = path / ".git" / "hooks"
    for name in ("pre-push", "post-checkout", "post-commit", "reference-transaction"):
        hook = hooks / name
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o755)
    monitor = path / "fsmon.sh"
    monitor.write_text(f"#!/bin/sh\ntouch {marker}\n")
    monitor.chmod(0o755)
    subprocess.run(["git", "-C", str(path), "config", "core.fsmonitor", str(monitor)], check=True)


def test_hooks_and_fsmonitor_do_not_run(tmp_path, monkeypatch):
    monkeypatch.undo()  # drops the autouse subprocess guard: this test really runs git on a local repo
    repo = tmp_path / "repo"
    marker = tmp_path / "ran"
    _init_repo(repo)
    _plant(repo, marker)
    marker.unlink(missing_ok=True)

    async def run():
        await github.git(repo, "status")
        await github.git(repo, "checkout", "--quiet", "--detach", "HEAD")
        await github.git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-qm", "x")

    asyncio.run(run())
    assert not marker.exists()


def test_ext_protocol_from_repo_config_is_refused(tmp_path, monkeypatch):
    monkeypatch.undo()
    repo = tmp_path / "repo"
    marker = tmp_path / "ran"
    _init_repo(repo)
    for key, value in (("protocol.ext.allow", "always"), ("remote.origin.url", f"ext::touch {marker}")):
        subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)

    with pytest.raises(github.GitHubError):
        asyncio.run(github.git(repo, "fetch", "origin"))
    assert not marker.exists()


def test_smudge_filter_cannot_read_the_token(tmp_path, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("GITHUB_TOKEN", "super-secret-token")
    repo = tmp_path / "repo"
    dump = tmp_path / "env.txt"
    _init_repo(repo)
    (repo / ".gitattributes").write_text("* filter=x\n")
    (repo / "f.txt").write_text("hello\n")
    subprocess.run(["git", "-C", str(repo), "config", "filter.x.smudge", f"sh -c 'env > {dump}'"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "core.hooksPath=/dev/null", "commit", "-qm", "f"], check=True)  # fmt: skip
    (repo / "f.txt").unlink()

    asyncio.run(github.git(repo, "checkout", "--quiet", "--force", "HEAD", "--", "f.txt"))
    assert dump.exists()  # the filter did run, so the check below means something
    assert "super-secret-token" not in dump.read_text()


def test_token_only_for_network_commands(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("ADMIN_TOKEN", "admin")
    seen = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, env, **kwargs):
        seen.append((args[3:], env))
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    async def run():
        url = "https://github.com/o/r"
        await github.git(".", "status", repo_url=url)
        await github.git(".", "push", "origin", "x", repo_url=url)

    asyncio.run(run())
    (status_args, status_env), (push_args, push_env) = seen
    assert "GIT_CONFIG_VALUE_0" not in status_env
    assert "GIT_CONFIG_VALUE_0" in push_env
    for env in (status_env, push_env):
        assert "GITHUB_TOKEN" not in env and "ADMIN_TOKEN" not in env
    assert "secret" not in "".join(status_env.values())
    for args, env in seen:
        assert args[: len(github.SAFE_GIT_CONFIG)] == github.SAFE_GIT_CONFIG
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
