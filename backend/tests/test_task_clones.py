"""Tasks and desks work in their own clone (--reference --dissociate), never in the reference."""

import asyncio
import os
import shlex
import shutil
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


def test_desk_filters_never_run(setup):
    project, reference, _ = setup
    (reference / ".gitattributes").write_text("* filter=x\n")
    (reference / "f.txt").write_text("x")
    _run("add", ".gitattributes", "f.txt", cwd=reference)
    _run("commit", "-q", "-m", "attrs", cwd=reference)
    _run("update-ref", "refs/remotes/origin/main", "HEAD", cwd=reference)
    employee = SimpleNamespace(id=3)
    path = asyncio.run(worktrees.prepare_desk(project, employee))
    marker = path.parent / "pwned"
    # The agent defines the filter the repository's .gitattributes names, and dirties the file
    _run("config", "filter.x.smudge", f"touch {marker}; cat", cwd=path)
    (path / "f.txt").write_text("changed")
    asyncio.run(worktrees.prepare_desk(project, employee))
    assert not marker.exists()
    assert (path / "f.txt").read_text() == "x"


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


def _alternates(name):
    def tamper(path):
        (path / ".git" / "objects" / "info" / name).write_text("/data/projects/project-9/repo/.git/objects\n")

    return tamper


def _commondir(path):
    (path / ".git" / "commondir").write_text("/data/projects/project-9/repo/.git\n")


def _symlinked_pack(path):
    pack = path / ".git" / "objects" / "pack"
    shutil.rmtree(pack)
    pack.symlink_to(path.parent / "elsewhere")


def _symlinked_pack_file(path):
    pack = path / ".git" / "objects" / "pack"
    pack.mkdir(exist_ok=True)
    (pack / "pack-x.pack").symlink_to(path.parent / "elsewhere")


def _symlinked_objects(path):
    objects = path / ".git" / "objects"
    shutil.rmtree(objects)
    objects.symlink_to(path.parent / "elsewhere")


def _gitfile(path):
    shutil.rmtree(path / ".git")
    (path / ".git").write_text("gitdir: /data/projects/project-9/repo/.git\n")


@pytest.mark.parametrize(
    "tamper",
    [
        _alternates("alternates"),
        _alternates("http-alternates"),
        _commondir,
        _symlinked_pack,
        _symlinked_pack_file,
        _symlinked_objects,
        _gitfile,
    ],
)
def test_push_refuses_a_clone_that_points_elsewhere(setup, tamper):
    project, reference, calls = setup
    task = SimpleNamespace(id=5, branch="task/5")
    _, path = asyncio.run(worktrees.prepare_worktree(project, task))
    task.worktree_path = str(path)
    _run("commit", "-q", "--allow-empty", "-m", "work", cwd=path)
    tamper(path)
    calls.clear()
    with pytest.raises(github.GitHubError, match="Refusing to push"):
        asyncio.run(worktrees.push_task_branch(project, task))
    assert calls == []  # Nothing ran, in particular no fetch from the clone
    assert "refs/heads/task/5" not in _run("for-each-ref", cwd=reference)


def test_clone_config_cannot_replace_upload_pack(setup):
    project, reference, _ = setup
    task = SimpleNamespace(id=5, branch="task/5")
    _, path = asyncio.run(worktrees.prepare_worktree(project, task))
    marker = path.parent / "pwned"
    # Regression guard: git already ignores `remote.<absolute path>.*` (a remote name cannot start
    # with `/`), so this passes without the flags too; they stay as defence in depth
    _run("config", f"remote.{reference}.uploadpack", f"touch {marker}; git-upload-pack", cwd=path)
    asyncio.run(worktrees.refresh_clone(project, path))
    assert not marker.exists()


def test_askpass_is_neutralised(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "secret")
    for url in (None, "https://github.com/acme/app"):
        env = github._git_env(url)
        assert env["GIT_ASKPASS"] == "/bin/true"
    assert "core.askPass=" in github.SAFE_GIT_CONFIG


def _foreign_dir(path):
    """What a rename leaves in a desk: a directory the backend cannot empty (cache moved in)."""
    cache = path / ".pytest_cache"
    cache.mkdir()
    (cache / "f").write_text("x")
    cache.chmod(0o555)
    return cache


@pytest.fixture
def restore_perms():
    made = []
    yield made
    for d in made:
        if d.exists():
            d.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can delete anything")
def test_desk_with_foreign_directory_is_recloned_through_the_agent(setup, monkeypatch, restore_perms):
    project, _, _ = setup
    employee = SimpleNamespace(id=3)
    path = asyncio.run(worktrees.prepare_desk(project, employee))
    restore_perms.append(_foreign_dir(path))
    calls = []

    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(*argv, **kw):
        if argv[0] != "sudo":
            return await real_exec(*argv, **kw)
        calls.append(argv)
        restore_perms[0].chmod(0o755)  # What the agent, owner of the directory, can do
        for child in Path(argv[-1]).iterdir():  # Contents only: the clone's parent is not the agent's
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
        return SimpleNamespace(returncode=0, communicate=lambda: asyncio.sleep(0, (b"", b"")))

    monkeypatch.setattr(worktrees.settings, "agent_user", "agent")
    monkeypatch.setattr(worktrees, "_share_with_group", lambda path: None)  # No work group on CI
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(worktrees.prepare_desk(project, employee))
    assert calls[0][:5] == ("sudo", "-n", "-u", "agent", "/usr/local/bin/palabre-rm-clone")
    assert not (path / ".pytest_cache").exists()
    assert (path / ".git").is_dir()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can delete anything")
def test_removal_failure_names_the_real_cause(setup, restore_perms):
    project, _, _ = setup
    employee = SimpleNamespace(id=3)
    path = asyncio.run(worktrees.prepare_desk(project, employee))
    restore_perms.append(_foreign_dir(path))
    with pytest.raises(worktrees.CloneRemovalError, match="cannot delete .*Permission denied"):
        asyncio.run(worktrees.prepare_desk(project, employee))


@pytest.mark.skipif(os.geteuid() == 0, reason="root can delete anything")
def test_task_worktree_removal_fails_loudly(setup, restore_perms):
    project, _, _ = setup
    task = SimpleNamespace(id=5, branch=None)
    _, path = asyncio.run(worktrees.prepare_worktree(project, task))
    restore_perms.append(_foreign_dir(path))
    with pytest.raises(worktrees.CloneRemovalError):
        asyncio.run(worktrees.remove_task_worktree(project, task))


def _assert_private_copy(path):
    objects = [p for p in (path / ".git" / "objects").rglob("*") if p.is_file()]
    assert objects
    for obj in objects:
        assert obj.stat().st_nlink == 1, obj
        assert obj.stat().st_mode & 0o040, obj  # readable by the group


def test_clones_share_no_object_with_the_reference(setup):
    project, reference, _ = setup
    (reference / "f.txt").write_text("x")
    _run("add", "f.txt", cwd=reference)
    _run("commit", "-q", "-m", "more", cwd=reference)
    _run("update-ref", "refs/remotes/origin/main", "HEAD", cwd=reference)
    for obj in (reference / ".git" / "objects").rglob("*"):
        if obj.is_file():
            obj.chmod(0o400)  # as in the real reference
    _, task_path = asyncio.run(worktrees.prepare_worktree(project, SimpleNamespace(id=5, branch=None)))
    _assert_private_copy(task_path)
    desk = SimpleNamespace(id=7)
    desk_path = asyncio.run(worktrees.prepare_desk(project, desk))
    _assert_private_copy(desk_path)
    _run("fsck", cwd=desk_path)
    assert all(
        obj.stat().st_mode & 0o777 == 0o400 for obj in (reference / ".git" / "objects").rglob("*") if obj.is_file()
    )


def _ls_remote(tmp_path, repo, command, **env):
    """ls-remote through an upload-pack command, with git's config isolated from the host's."""
    return subprocess.run(
        ["git", "-C", str(tmp_path), "ls-remote", f"--upload-pack={command}", str(repo)],
        capture_output=True, text=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            # Makes git treat every repo as foreign-owned, so only the exact safe.directory entry passes
            "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
            **env,
        },
    )  # fmt: skip


def test_upload_pack_trusts_only_the_exact_clone(tmp_path):
    # Git drops -c and GIT_CONFIG_* for the upload-pack of a local fetch: the command carries them
    command = github.upload_pack_command("/data/a b")
    words = shlex.split(command)
    assert words[0] == "git" and words[-1] == "upload-pack"
    assert "safe.directory=/data/a b/.git" in words and "safe.directory=*" not in words
    assert "safe.directory=/data/a b" not in words
    assert "core.hooksPath=/dev/null" in words and "core.fsmonitor=false" in words
    # And it is a working upload-pack
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=n", "-c", "user.email=e@x", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    out = _ls_remote(tmp_path, repo, github.upload_pack_command(repo))
    assert out.returncode == 0 and "HEAD" in out.stdout
    # Without any safe.directory entry the foreign-owned repo is refused (the env var proves the entry matters)
    bare = shlex.join(["git", "upload-pack"])
    refused = _ls_remote(tmp_path, repo, bare)
    if refused.returncode == 0:
        pytest.skip("this git ignores GIT_TEST_ASSUME_DIFFERENT_OWNER: cannot prove the entry matters")
    assert "HEAD" not in refused.stdout


def test_upload_pack_command_runs_under_the_account():
    words = shlex.split(github.upload_pack_command("/data/projects/project-1/worktrees/task-5", "agent2"))
    assert words == ["sudo", "-n", "-u", "agent2", github.UPLOAD_PACK_SCRIPT]


def test_upload_pack_script_refuses_other_paths():
    script = Path(__file__).resolve().parents[1] / "scripts" / "upload-pack.sh"
    for bad in ("/data/projects/project-2/repo", "/data/projects/project-1/worktrees/task-5/../..", "/etc", "relative", "/data/projects/project-1/worktrees/task-5\n/x"):
        out = subprocess.run(["sh", str(script), bad], capture_output=True, text=True)
        assert out.returncode == 2 and "not a task clone path" in out.stderr, bad


@pytest.fixture
def agent_pool_env(setup, monkeypatch, tmp_path):
    """The push as the pool does it: the clone owned by `agent1` (faked), sudo replaced by a shim
    that drops `-n -u <user>` and runs a stand-in for the root script."""
    project, reference, calls = setup
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "sudo.log"
    (bin_dir / "sudo").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {log}\nshift 3\nexec \"$@\"\n")
    # The real root script, with the path prefix swapped for the test's tmp dir, so its git command line is exercised
    real = (Path(__file__).parent.parent / "scripts" / "upload-pack.sh").read_text()
    (bin_dir / "palabre-upload-pack").write_text(real.replace("^/data/projects/", f"^{tmp_path}/projects/"))
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(github, "UPLOAD_PACK_SCRIPT", str(bin_dir / "palabre-upload-pack"))
    monkeypatch.setattr(worktrees, "UPLOAD_PACK_SCRIPT", str(bin_dir / "palabre-upload-pack"))
    monkeypatch.setattr(settings, "agent_user", "agent")
    monkeypatch.setattr(settings, "agent_pool_size", 2)
    owner = SimpleNamespace(pw_name="agent1")
    monkeypatch.setattr(worktrees.pwd, "getpwuid", lambda uid: owner)
    task = SimpleNamespace(id=5, branch="task/5")
    _, path = asyncio.run(worktrees.prepare_worktree(project, task))
    task.worktree_path = str(path)
    _run("commit", "-q", "--allow-empty", "-m", "work", cwd=path)
    return project, reference, task, log, owner


def test_push_fetches_as_the_clone_owner(agent_pool_env, monkeypatch):
    project, reference, task, log, _ = agent_pool_env
    seen = []

    async def spy(cwd, *args, **kwargs):
        if args[0] == "update-ref" and args[1] == "-d":  # Before the ref is dropped
            seen.append(_run("rev-parse", "--verify", "refs/heads/task/5", cwd=reference).strip())
        return await worktrees_git(cwd, *args, **kwargs)

    worktrees_git = worktrees.git
    monkeypatch.setattr(worktrees, "git", spy)
    asyncio.run(worktrees.push_task_branch(project, task))
    assert seen  # The branch was served by the account's upload-pack
    assert log.read_text().split()[:3] == ["-n", "-u", "agent1"]


def test_push_fails_closed_when_the_clone_was_taken_back(agent_pool_env, monkeypatch):
    project, reference, task, log, owner = agent_pool_env
    owner.pw_name = "palabre"
    with pytest.raises(github.GitHubError, match="owned by palabre.*taken back"):
        asyncio.run(worktrees.push_task_branch(project, task))
    assert not log.exists()  # Never fell back to reading it as the backend
    assert "refs/heads/task/5" not in _run("for-each-ref", cwd=reference)


def test_push_fails_when_sudo_is_unavailable(agent_pool_env, monkeypatch):
    project, _, task, log, _ = agent_pool_env
    monkeypatch.setattr(worktrees, "UPLOAD_PACK_SCRIPT", "/nonexistent/palabre-upload-pack")
    with pytest.raises(github.GitHubError, match="sudo or /nonexistent/palabre-upload-pack is unavailable"):
        asyncio.run(worktrees.push_task_branch(project, task))
    assert not log.exists()


def _commit_with_dotgit_entry(path):
    blob = subprocess.run(
        [*G, "hash-object", "-w", "--stdin"], cwd=path, check=True, capture_output=True, input=b"",
    ).stdout.decode().strip()  # fmt: skip
    # A tree entry named .git: hasDotgit is an error for fsck, plain transfer accepts it
    tree = subprocess.run(
        [*G, "hash-object", "-w", "-t", "tree", "--literally", "--stdin"], cwd=path, check=True,
        capture_output=True, input=b"100644 .git\0" + bytes.fromhex(blob),
    ).stdout.decode().strip()  # fmt: skip
    return _run("commit-tree", tree, "-m", "bad", cwd=path).strip()


def test_malformed_object_is_only_refused_by_fsck(agent_pool_env, tmp_path):
    _, _, task, _, _ = agent_pool_env
    path = Path(task.worktree_path)
    commit = _commit_with_dotgit_entry(path)
    _run("update-ref", "refs/heads/task/5", commit, cwd=path)
    # Counterpart: without the fsck setting the very same commit is fetched
    plain = tmp_path / "plain"
    _run("init", "-q", str(plain), cwd=tmp_path)
    _run("-c", "protocol.file.allow=always", "fetch", "-q", str(path), "refs/heads/task/5", cwd=plain)
    _run("cat-file", "-e", commit, cwd=plain)
    strict = tmp_path / "strict"
    _run("init", "-q", str(strict), cwd=tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        _run("-c", "protocol.file.allow=always", "-c", "transfer.fsckObjects=true", "fetch", "-q", str(path),
             "refs/heads/task/5", cwd=strict)  # fmt: skip


def test_push_refuses_a_malformed_object(agent_pool_env):
    project, reference, task, _, _ = agent_pool_env
    path = Path(task.worktree_path)
    commit = _commit_with_dotgit_entry(path)
    _run("update-ref", "refs/heads/task/5", commit, cwd=path)
    with pytest.raises(github.GitHubError, match="fetch failed"):
        asyncio.run(worktrees.push_task_branch(project, task))
    assert "refs/heads/task/5" not in _run("for-each-ref", cwd=reference)

def test_remove_project_files_logs_what_it_cannot_delete(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    root = tmp_path / "projects" / "project-3"
    (root / "repo").mkdir(parents=True)
    (root / "repo" / "a.txt").write_text("x")

    def fake_rmtree(path, onexc=None, **_kw):
        onexc(os.unlink, str(Path(path) / "repo" / "a.txt"), PermissionError("denied"))

    monkeypatch.setattr(worktrees.shutil, "rmtree", fake_rmtree)
    with caplog.at_level("ERROR", logger="app.worktrees"):
        asyncio.run(worktrees.remove_project_files(3))  # does not raise
    assert "cannot delete" in caplog.text and "a.txt" in caplog.text and "denied" in caplog.text


def test_remove_project_files_removes_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "projects_dir", tmp_path / "projects")
    (tmp_path / "projects" / "project-4" / "repo").mkdir(parents=True)
    asyncio.run(worktrees.remove_project_files(4))
    assert not (tmp_path / "projects" / "project-4").exists()


def _rm_clone(tmp_path, root, path):
    conf = tmp_path / "conf"
    conf.write_text(root)
    script = Path(__file__).parent.parent / "scripts" / "rm-clone.sh"
    env = {**os.environ, "PALABRE_RM_CLONE_CONF": str(conf)}
    return subprocess.run(["sh", str(script), str(path)], env=env, capture_output=True, text=True)


def test_rm_clone_root_comes_from_config(tmp_path):
    script = (Path(__file__).parent.parent / "scripts" / "rm-clone.sh").read_text()
    assert "/data/projects" not in script
    root = tmp_path / "projs"
    clone = root / "project-1" / "worktrees" / "task-2"
    clone.mkdir(parents=True)
    (clone / "f").write_text("x")
    done = _rm_clone(tmp_path, str(root), clone)
    assert done.returncode == 0, done.stderr
    assert clone.is_dir() and not any(clone.iterdir())


def test_rm_clone_refuses_outside_the_root(tmp_path):
    root = tmp_path / "projs"
    other = tmp_path / "other" / "project-1" / "worktrees" / "task-2"
    other.mkdir(parents=True)
    (other / "f").write_text("x")
    done = _rm_clone(tmp_path, str(root), other)
    assert done.returncode == 2 and (other / "f").exists()


def test_rm_clone_fails_closed_on_bad_root(tmp_path):
    clone = tmp_path / "projs" / "project-1" / "worktrees" / "task-2"
    clone.mkdir(parents=True)
    (clone / "f").write_text("x")
    for root in ("", "/", "relative", f"{tmp_path}/projs/"):
        assert _rm_clone(tmp_path, root, clone).returncode == 2
    assert (clone / "f").exists()
    # No config file at all
    script = Path(__file__).parent.parent / "scripts" / "rm-clone.sh"
    env = {**os.environ, "PALABRE_RM_CLONE_CONF": str(tmp_path / "missing")}
    assert subprocess.run(["sh", str(script), str(clone)], env=env, capture_output=True).returncode == 2
