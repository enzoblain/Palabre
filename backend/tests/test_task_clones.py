"""Tasks and desks work in their own clone (--reference --dissociate), never in the reference."""

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import github, worktrees
from app.config import settings

G = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.hooksPath=/dev/null"]


def _run(*args, cwd):
    return subprocess.run([*G, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.undo()  # drops the autouse subprocess guard: real git on local repos
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    project = SimpleNamespace(id=1, repo_url="https://github.com/acme/app", default_branch="main")
    reference = worktrees.repo_dir(project)
    reference.mkdir(parents=True)
    _run("init", "-q", "-b", "main", cwd=reference)
    _run("commit", "-q", "--allow-empty", "-m", "init", cwd=reference)
    _run("update-ref", "refs/remotes/origin/main", "HEAD", cwd=reference)
    real_git = github.git
    calls = []

    async def git(cwd, *args, **kwargs):
        calls.append((args, kwargs))
        kwargs.pop("cwd", None)
        if kwargs.get("repo_url"):  # No network in tests
            calls.append(("token-in", str(cwd)))
            return ""
        if args[:3] == ("remote", "set-url", "origin"):
            return ""  # Keep the local origin the clone was made from
        return await real_git(cwd, *args, **kwargs)

    monkeypatch.setattr(worktrees, "git", git)

    async def no_sync(_project):
        return reference

    monkeypatch.setattr(worktrees, "_sync_repo", no_sync)
    return project, reference, calls


def test_task_clone_is_independent_of_the_reference(setup):
    project, reference, calls = setup
    task = SimpleNamespace(id=5, branch=None)
    branch, path = asyncio.run(worktrees.prepare_worktree(project, task))
    assert branch == "task/5"
    assert (path / ".git").is_dir()  # a real clone, not a linked worktree
    assert not (path / ".git" / "objects" / "info" / "alternates").exists()  # --dissociate
    assert _run("rev-parse", "--abbrev-ref", "HEAD", cwd=path).strip() == "task/5"
    assert "refs/heads/task/5" not in _run("for-each-ref", cwd=reference)
    assert "worktrees" not in {p.name for p in (reference / ".git").iterdir()}
    clone_call = next(c for c in calls if c[0] and c[0][0] == "clone")
    assert clone_call[1] == {"allow_file": True}
    # The local transport is for the clone and for fetches from the reference, never with the token
    assert all(args[0] in {"clone", "fetch"} and not kw.get("repo_url") for args, kw in calls if kw.get("allow_file"))


def test_existing_clone_is_kept(setup):
    project, _, _ = setup
    task = SimpleNamespace(id=5, branch="task/5")
    _, path = asyncio.run(worktrees.prepare_worktree(project, task))
    (path / "wip.txt").write_text("x")
    asyncio.run(worktrees.prepare_worktree(project, task))
    assert (path / "wip.txt").exists()


def test_rename_branch_and_commits_ahead_work_in_the_clone(setup):
    project, reference, _ = setup
    task = SimpleNamespace(id=5, branch=None)
    _, path = asyncio.run(worktrees.prepare_worktree(project, task))
    task.worktree_path = str(path)
    _run("commit", "-q", "--allow-empty", "-m", "work", cwd=path)
    asyncio.run(worktrees.rename_branch(task, "feat/5-x"))
    assert task.branch == "feat/5-x"
    assert _run("rev-parse", "--abbrev-ref", "HEAD", cwd=path).strip() == "feat/5-x"
    assert "feat/5-x" not in _run("for-each-ref", cwd=reference)
    ahead = asyncio.run(github.git(path, "rev-list", "--count", "origin/main..HEAD"))
    assert ahead.strip() == "1"


def test_remove_deletes_the_clone(setup):
    project, _, _ = setup
    task = SimpleNamespace(id=5, branch=None)
    _, path = asyncio.run(worktrees.prepare_worktree(project, task))
    asyncio.run(worktrees.remove_task_worktree(project, task))
    assert not path.exists()


def test_desk_is_reset_at_each_run(setup):
    project, _, _ = setup
    employee = SimpleNamespace(id=3)
    path = asyncio.run(worktrees.prepare_desk(project, employee))
    (path / "junk.txt").write_text("x")
    asyncio.run(worktrees.prepare_desk(project, employee))
    assert not (path / "junk.txt").exists()
    assert (path / ".git").is_dir()


def test_failed_clone_leaves_nothing(setup, monkeypatch):
    project, reference, _ = setup
    project_path = Path(worktrees.project_dir(project)) / "worktrees" / "task-9"

    async def boom(*_, **__):
        raise github.GitHubError("nope")

    monkeypatch.setattr(worktrees, "git", boom)
    with pytest.raises(github.GitHubError):
        asyncio.run(worktrees.prepare_worktree(project, SimpleNamespace(id=9, branch=None)))
    assert not project_path.exists()


def test_file_transport_only_when_asked(monkeypatch):
    seen = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, env, **kwargs):
        seen.append((args, env))
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(github.git("/a", "status"))
    asyncio.run(github.git("/a", "clone", "x", "y", allow_file=True))
    (plain, plain_env), (clone, clone_env) = seen
    assert plain_env["GIT_ALLOW_PROTOCOL"] == "https"
    assert clone_env["GIT_ALLOW_PROTOCOL"] == "https:file"
    assert "protocol.file.allow=always" not in plain and "protocol.file.allow=always" in clone
    assert "safe.directory=/a" in plain and "safe.directory=/a" in clone


def test_token_never_runs_in_an_agent_clone(setup):
    project, reference, calls = setup
    task = SimpleNamespace(id=5, branch="task/5")
    _, path = asyncio.run(worktrees.prepare_worktree(project, task))
    task.worktree_path = str(path)
    # The agent points origin at another private repository
    _run("remote", "set-url", "origin", "https://github.com/acme/other-private", cwd=path)
    _run("config", "url.https://github.com/acme/other-private.insteadOf", str(reference), cwd=path)
    _run("commit", "-q", "--allow-empty", "-m", "work", cwd=path)
    calls.clear()
    for step in (
        worktrees.refresh_clone(project, path),
        worktrees.prepare_worktree(project, task),
        worktrees.prepare_desk(project, SimpleNamespace(id=3)),
        worktrees.push_task_branch(project, task),
    ):
        try:
            asyncio.run(step)
        except github.GitHubError:
            pass  # A rewritten URL may break the agent's own clone, but it carries no token
    token_cwds = {c[1] for c in calls if c[0] == "token-in"}
    assert token_cwds == {str(reference)}
    assert "refs/heads/task/5" not in _run("for-each-ref", cwd=reference)  # pushed from a temporary ref


def test_askpass_is_neutralised(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "secret")
    for url in (None, "https://github.com/acme/app"):
        env = github._git_env(url)
        assert env["GIT_ASKPASS"] == "/bin/true"
    assert "core.askPass=" in github.SAFE_GIT_CONFIG
