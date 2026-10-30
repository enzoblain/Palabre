"""Local clone of each project's repository (the reference), and one clone per task and per desk."""

import asyncio
import logging
import os
import pwd
import re
import shutil
import stat
from collections import defaultdict
from pathlib import Path

from app import agent_pool, claude_store
from app.config import settings
from app.github import BRANCH_PATTERN, UPLOAD_PACK_SCRIPT, GitHubError, git, repo_slug, resolve_branch, upload_pack_command
from app.models import Employee, Project, Task

log = logging.getLogger(__name__)

# One git operation at a time on a project's main clone (clone, fetch, and every clone made from it)
_repo_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def project_dir(project: Project) -> Path:
    return settings.projects_dir / f"project-{project.id}"


async def remove_project_files(project_id: int) -> None:
    """Everything a project left on disk: clone, task clones, desks, and the agents'
    Claude sessions. The GitHub repository itself is not touched. A path that cannot be
    removed is logged, never raised: the project is deleted anyway."""

    def remove(target: Path) -> None:
        def failed(_func, path, exc: BaseException) -> None:
            log.error("Project %s: cannot delete %s: %s", project_id, path, exc)

        if target.exists() or target.is_symlink():
            shutil.rmtree(target, onexc=failed)
    targets = [settings.projects_dir / f"project-{project_id}", *claude_store.session_dirs(project_id)]
    async with _repo_locks[project_id]:
        for target in targets:
            await asyncio.to_thread(remove, target)
    _repo_locks.pop(project_id, None)


def repo_dir(project: Project) -> Path:
    return project_dir(project) / "repo"


async def sync_repo(project: Project) -> Path:
    """Clone the repository if needed, fetch, and put the main checkout on the default branch.

    The main checkout is read-only for agents (conversation runs read code there).
    """
    async with _repo_locks[project.id]:
        return await _sync_repo(project)


async def _sync_repo(project: Project) -> Path:
    repo = repo_dir(project)
    if not (repo / ".git").exists():
        # Agents cross the project's directory but cannot rename anything in it
        repo.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        await git(repo.parent, "clone", "--quiet", project.repo_url, str(repo), repo_url=project.repo_url)
    else:
        await git(repo, "fetch", "--quiet", "--prune", "origin", repo_url=project.repo_url)
    # The reference holds the GitHub remote: the backend alone reads it (agents clone from a
    # copy made by the backend, see _clone_from_reference)
    repo.chmod(0o700)
    branch = project.default_branch
    if not await _has_ref(repo, f"refs/remotes/origin/{branch}"):
        if (await git(repo, "branch", "--remotes")).strip():
            raise GitHubError(f"The branch '{branch}' does not exist on GitHub (project's default branch)")
        await _initial_commit(project, repo)
    await git(repo, "checkout", "--quiet", "--force", "--detach", f"refs/remotes/origin/{branch}")
    return repo


async def _has_ref(repo: Path, ref: str) -> bool:
    try:
        await git(repo, "rev-parse", "--verify", "--quiet", ref)
        return True
    except GitHubError:
        return False


INITIAL_GITIGNORE = """.env
.venv/
__pycache__/
node_modules/
.DS_Store
"""


def initial_readme(project: Project) -> str:
    return f"# {project.name}\n\nProject started with Palabre. Describe the product and how to run it here.\n"


async def _initial_commit(project: Project, repo: Path) -> None:
    """A brand-new GitHub repository has no commit: tasks need a branch to start from, so
    a first commit (minimal README and .gitignore) is pushed. Production (the repository's default branch) comes
    first, as the first branch pushed becomes the default; a working branch other than
    production (`dev`) then starts from the same commit."""
    branch = project.default_branch
    production = await resolve_branch(repo_slug(project.repo_url), "")
    # Already made by an attempt whose push failed: only the pushes are left
    if not await _has_ref(repo, f"refs/heads/{production}"):
        await git(repo, "checkout", "--quiet", "--orphan", production)
        (repo / "README.md").write_text(initial_readme(project))
        (repo / ".gitignore").write_text(INITIAL_GITIGNORE)
        await git(repo, "add", "README.md", ".gitignore")
        await git(
            repo, "-c", "user.name=Palabre", "-c", "user.email=palabre@palabre.local",
            "commit", "--quiet", "-m", "Initial commit",
        )  # fmt: skip
    for name in dict.fromkeys([production, branch]):
        await git(repo, "push", "--quiet", "origin", f"{production}:refs/heads/{name}", repo_url=project.repo_url)
    await git(repo, "fetch", "--quiet", "origin", repo_url=project.repo_url)


async def commit_release(project: Project, expected_sha: str, files: dict[str, str], message: str) -> str:
    """One commit with `files` (path to text) on top of the team's branch, pushed to that branch only
    (never production, no force): refused if the branch is no longer at `expected_sha`. Returns the new SHA."""
    branch = project.default_branch
    if not re.fullmatch(BRANCH_PATTERN, branch) or branch == await resolve_branch(repo_slug(project.repo_url), ""):
        raise GitHubError(f"Refusing to commit a release on '{branch}'")
    async with _repo_locks[project.id]:
        repo = await _sync_repo(project)
        if (await git(repo, "rev-parse", "HEAD")).strip() != expected_sha:
            raise GitHubError(f"{branch} moved while the release was prepared")
        for path, text in files.items():
            target = repo / path
            # A symlink (the file or a folder above it) could send the write elsewhere
            if not target.resolve().is_relative_to(repo.resolve()) or any(p.is_symlink() for p in (target, *target.parents) if p != repo and repo in p.parents):
                raise GitHubError(f"Refusing to write outside the repository: {path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        await git(repo, "add", "--", *files)
        await git(
            repo, "-c", "user.name=Palabre", "-c", "user.email=palabre@palabre.local",
            "commit", "--quiet", "-m", message,
        )  # fmt: skip
        sha = (await git(repo, "rev-parse", "HEAD")).strip()
        # A plain push of this commit to the team's branch: GitHub refuses it if the branch moved
        await git(repo, "push", "--quiet", "origin", f"{sha}:refs/heads/{branch}", repo_url=project.repo_url)
        return sha


class CloneRemovalError(GitHubError):
    pass


async def _remove_clone(path: Path) -> None:
    """Delete a desk or task clone and check it is gone. The agent runs as another user: what
    it created outside the shared group (a renamed cache directory...) the backend cannot
    delete, so the leftovers are emptied by the narrow `palabre-rm-clone` sudo rule (the
    agent cannot unlink the clone itself: its parent is the backend's). Without that the
    clone would fail later on a non-empty destination, hiding the real cause."""
    errors: list[str] = []

    def remove() -> None:
        # Keep going past the first denied entry, so the agent pass has less to do
        shutil.rmtree(path, onexc=lambda _f, _p, exc: errors.append(str(exc)))

    await asyncio.to_thread(remove)
    # Any pool user may have written in the clone over time: each empties what it owns
    for user in agent_pool.users():
        if not path.exists():
            break
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "-u", user, "/usr/local/bin/palabre-rm-clone", str(path),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        _, stderr = await proc.communicate()
        if proc.returncode:
            errors.append(f"as {user}: {stderr.decode(errors='replace').strip()}")
        else:
            errors.clear()
            await asyncio.to_thread(remove)
    if path.exists():
        raise CloneRemovalError(f"cannot delete {path}: {'; '.join(errors[:3]) or 'still present'}")


def desk_dir(project: Project, employee: Employee) -> Path:
    return project_dir(project) / "desks" / f"employee-{employee.id}"


async def _clone_from_reference(project: Project, path: Path) -> None:
    """An independent clone of the project: objects borrowed from the reference then copied
    (--dissociate), so the agent never writes to the reference. Objects are copied, never
    hard-linked (--no-hardlinks): links would share the reference's private modes and inodes.
    The clone reads the local path (the only call allowed the file transport), then points
    at GitHub and fetches its branches.
    Expects the repo lock held."""
    # The directory holding the clones is closed to agents: they write inside their clone only
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    path.parent.chmod(0o2755)
    reference = repo_dir(project)
    # Closed before the clone fills it: the work group never sees a writable window (#160)
    path.mkdir(mode=0o700, exist_ok=True)
    path.chmod(0o700)
    try:
        await git(
            path.parent, "clone", "--quiet", "--no-hardlinks", "--reference", str(reference), "--dissociate", str(reference),
            str(path),
            allow_file=True,
        )  # fmt: skip
        await git(path, "remote", "set-url", "origin", project.repo_url)
        await _pull_from_reference(project, path)
    except GitHubError:
        await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)  # Never leave a half clone
        raise


async def _pull_from_reference(project: Project, path: Path) -> None:
    """Bring the clone's origin/* up to date from the reference over the local transport. The
    clone's config is written by the agent (remote URL, insteadOf...): no command carrying the
    token ever runs there. Expects the repo lock held and the reference synced.

    The command line beats the clone's config: `remote.<path>.uploadpack` would otherwise run
    an agent command, and submodule recursion would fetch inside agent-written repos."""
    await git(
        path, "fetch", "--quiet", "--prune", "--upload-pack=git-upload-pack", "--no-recurse-submodules",
        str(repo_dir(project)), "+refs/remotes/origin/*:refs/remotes/origin/*",
        allow_file=True,
    )  # fmt: skip


async def refresh_clone(project: Project, path: Path) -> None:
    """Fetch GitHub into the reference, then the reference into the clone. Best effort: on a
    GitHub error the clone keeps the last fetched state."""
    async with _repo_locks[project.id]:
        try:
            await _sync_repo(project)
        except GitHubError:
            pass
        await _pull_from_reference(project, path)


def _clone_indirection(path: Path) -> str | None:
    """Why the clone's object store cannot be trusted, or None. Defence in depth behind the
    per-account upload-pack (#193): alternates, `commondir`, symlinks and gitfiles would
    otherwise serve another project's objects."""
    git_dir = path / ".git"
    if not stat.S_ISDIR(git_dir.lstat().st_mode):
        return ".git is not a real directory"
    for name in ("objects/info/alternates", "objects/info/http-alternates", "commondir"):
        if os.path.lexists(git_dir / name):
            return f"it has {name}"
    # scandir follows a symlink given as argument, so `objects` itself is checked first
    if not stat.S_ISDIR((git_dir / "objects").lstat().st_mode):
        return "objects is not a real directory"
    pending = [git_dir / "objects"]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if entry.is_symlink():
                    return f"{Path(entry.path).relative_to(git_dir)} is a symlink"
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
    return None


async def _require_isolated_clone(path: Path) -> None:
    """Fail closed: refuse to read a clone that points outside itself, with a clear error."""
    try:
        reason = await asyncio.to_thread(_clone_indirection, path)
    except OSError as exc:
        reason = f"its object store cannot be inspected ({exc})"
    if reason:
        raise GitHubError(
            f"Refusing to push: {reason}, which could pull in objects from another repository. "
            "Fix the clone (remove the file or symlink, keep .git a plain directory) and submit again."
        )


def _clone_owner_account(path: Path) -> str | None:
    """The agent account the push fetch must run as, or None when agents share the backend's
    user (no agent user configured). Fails closed: a pool clone not owned by a pool account was
    taken back (or never claimed), and serving it as another user would be the very thing this avoids."""
    if not settings.agent_user:
        return None
    if settings.agent_pool_size <= 0:
        return settings.agent_user  # Legacy shared account: clones are owned by the backend, shared through group work
    try:
        uids = {os.lstat(path).st_uid, os.lstat(path / ".git").st_uid}
        names = {pwd.getpwuid(uid).pw_name for uid in uids}
    except (OSError, KeyError) as exc:
        raise GitHubError(f"Refusing to push: cannot determine who owns the clone ({exc}).") from exc
    if len(names) != 1 or not names <= set(agent_pool.users()) - {settings.agent_user}:
        raise GitHubError(
            f"Refusing to push: the clone is owned by {', '.join(sorted(names))}, not by an agent account "
            "(it was taken back after the run). Run the task's agent again, then submit."
        )
    return names.pop()


def _require_sudo_upload_pack() -> None:
    if shutil.which("sudo") is None or not os.access(UPLOAD_PACK_SCRIPT, os.X_OK):
        raise GitHubError(
            f"Refusing to push: sudo or {UPLOAD_PACK_SCRIPT} is unavailable, and the clone is not read as the backend user."
        )


async def push_task_branch(project: Project, task: Task) -> None:
    """Publish the task's branch. The agent clone is only read, over the local transport; the
    push itself runs from the reference, whose config the backend owns, so the token never
    meets agent-written config. The lease is checked against the reference's origin/<branch>."""
    ref = f"refs/heads/{task.branch}"
    async with _repo_locks[project.id]:
        reference = repo_dir(project)
        clone = Path(task.worktree_path)
        user = _clone_owner_account(clone)
        if user:
            _require_sudo_upload_pack()
        await _require_isolated_clone(clone)  # Inside the lock, right before the fetch
        # fsckObjects: the fetch runs as the backend, so a malformed pack (booby-trapped .gitmodules,
        # symlinked paths) is refused here, before anything leaves for GitHub
        await git(
            reference, "fetch", "--quiet", "--no-tags", f"--upload-pack={upload_pack_command(clone, user)}",
            task.worktree_path, f"+{ref}:{ref}",
            allow_file=True, trust=clone / ".git", config=("transfer.fsckObjects=true",),
        )  # fmt: skip
        try:
            # Shrinks the window for a late write. On failure the fetched objects stay unreferenced
            # in the reference until gc: harmless, they cannot be pushed without a ref.
            await _require_isolated_clone(Path(task.worktree_path))
            await git(
                reference, "push", "--quiet", "--force-with-lease", "origin", f"{ref}:{ref}",
                repo_url=project.repo_url,
            )  # fmt: skip
            await git(reference, "fetch", "--quiet", "origin", repo_url=project.repo_url)
        finally:
            await git(reference, "update-ref", "-d", ref)
        await _pull_from_reference(project, Path(task.worktree_path))


async def prepare_desk(project: Project, employee: Employee) -> Path:
    """The employee's own scratch clone, where they work during conversations (read,
    run commands, test a task's branch). It is cloned afresh at every run and never pushed:
    real changes go through tasks. Expects the repository synced.

    Never reset an existing desk in place: checkout and clean run the clone's filters
    (`filter.x.smudge` in its agent-written config plus `.gitattributes`), i.e. agent code."""
    ref = f"refs/remotes/origin/{project.default_branch}"
    path = desk_dir(project, employee)
    async with _repo_locks[project.id]:
        await _remove_clone(path)
        await _clone_from_reference(project, path)  # Config written by the backend alone
        await git(path, "checkout", "--quiet", "--detach", ref)
    return path


async def remove_task_worktree(project: Project, task: Task) -> None:
    """A merged task's clone is of no use any more, and its branch went with it."""
    path = project_dir(project) / "worktrees" / f"task-{task.id}"
    async with _repo_locks[project.id]:
        await _remove_clone(path)
        # Tasks started before clones were linked worktrees; dead code once none is left
        await git(repo_dir(project), "worktree", "prune")


def branch_name(task: Task) -> str:
    return f"task/{task.id}"  # Not from the title, which is in the team's language


def final_branch_name(pr_title: str, task_id: int) -> str:
    """`<type>/<id>-<slug>` from the English Conventional Commits title (`feat(usage): show
    usage (#60)` → `feat/60-show-usage`); the slug is capped at 40 characters. Only the first
    submission names the branch: a later change of type in the title does not rename it."""
    kind, _, rest = pr_title.partition(": ")
    kind = re.split(r"[(!]", kind)[0]
    words = re.sub(r"\s*\(#\d+\)$", "", rest).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", words).strip("-")[:40].strip("-")
    return f"{kind}/{task_id}-{slug}" if slug else f"{kind}/{task_id}"


async def rename_branch(task: Task, new: str) -> None:
    """Rename the task's branch (checked out in its clone) before its first push.
    Idempotent: the source is the clone's actual branch, so a rename whose transaction was
    rolled back (the push failed afterwards) is not attempted twice."""
    current = (await git(task.worktree_path, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    if current != new:
        await git(task.worktree_path, "branch", "-m", current, new)
    task.branch = new


async def prepare_worktree(project: Project, task: Task) -> tuple[str, Path]:
    """The task's branch and clone, created from the default branch on first use (or from the
    branch if it is already on GitHub). An existing clone is kept as is: it holds the
    assignee's work in progress."""
    branch = task.branch or branch_name(task)
    path = project_dir(project) / "worktrees" / f"task-{task.id}"
    if path.exists():
        # Agents have no credentials: the backend keeps origin/* current for their rebases
        await refresh_clone(project, path)
        return branch, path

    async with _repo_locks[project.id]:
        await _sync_repo(project)
        await _clone_from_reference(project, path)
        try:
            # Fresh clone only: a checkout in an existing agent clone would run its filters
            if await _has_ref(path, f"refs/remotes/origin/{branch}"):
                await git(path, "checkout", "--quiet", "-B", branch, "--track", f"origin/{branch}")
            else:
                await git(path, "checkout", "--quiet", "-b", branch, f"origin/{project.default_branch}")
        except GitHubError:
            await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
            raise
    return branch, path
