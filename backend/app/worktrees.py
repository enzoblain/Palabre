"""Local clone of each project's repository (the reference), and one clone per task and per desk."""

import asyncio
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path

from app.config import settings
from app.github import GitHubError, git, repo_slug, resolve_branch
from app.models import Employee, Project, Task


# One git operation at a time on a project's main clone (clone, fetch, and every clone made from it)
_repo_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def project_dir(project: Project) -> Path:
    return settings.projects_dir / f"project-{project.id}"


def _claude_session_dirs(project_id: int) -> list[Path]:
    """Claude keeps each working directory's sessions in projects/<path with - for />."""
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
    prefix = re.sub(r"[^A-Za-z0-9]", "-", str(settings.projects_dir / f"project-{project_id}"))
    if not root.is_dir():
        return []
    return [d for d in root.iterdir() if d.name == prefix or d.name.startswith(prefix + "-")]


async def remove_project_files(project_id: int) -> None:
    """Everything a project left on disk: clone, task clones, desks, and the agents'
    Claude sessions. The GitHub repository itself is not touched."""
    targets = [settings.projects_dir / f"project-{project_id}", *_claude_session_dirs(project_id)]
    async with _repo_locks[project_id]:
        for target in targets:
            await asyncio.to_thread(shutil.rmtree, target, ignore_errors=True)
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
        repo.parent.mkdir(parents=True, exist_ok=True)
        await git(repo.parent, "clone", "--quiet", project.repo_url, str(repo), repo_url=project.repo_url)
    else:
        await git(repo, "fetch", "--quiet", "--prune", "origin", repo_url=project.repo_url)
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


def desk_dir(project: Project, employee: Employee) -> Path:
    return project_dir(project) / "desks" / f"employee-{employee.id}"


async def _clone_from_reference(project: Project, path: Path) -> None:
    """An independent clone of the project: objects borrowed from the reference then copied
    (--dissociate), so the agent never writes to the reference. The clone reads the local path
    (the only call allowed the file transport), then points at GitHub and fetches its branches.
    Expects the repo lock held."""
    path.parent.mkdir(parents=True, exist_ok=True)
    reference = repo_dir(project)
    try:
        await git(
            path.parent, "clone", "--quiet", "--reference", str(reference), "--dissociate", str(reference), str(path),
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
    token ever runs there. Expects the repo lock held and the reference synced."""
    await git(
        path, "fetch", "--quiet", "--prune", str(repo_dir(project)), "+refs/remotes/origin/*:refs/remotes/origin/*",
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


async def push_task_branch(project: Project, task: Task) -> None:
    """Publish the task's branch. The agent clone is only read, over the local transport; the
    push itself runs from the reference, whose config the backend owns, so the token never
    meets agent-written config. The lease is checked against the reference's origin/<branch>."""
    ref = f"refs/heads/{task.branch}"
    async with _repo_locks[project.id]:
        reference = repo_dir(project)
        await git(
            reference, "fetch", "--quiet", "--no-tags", task.worktree_path, f"+{ref}:{ref}",
            allow_file=True, trust=task.worktree_path,
        )  # fmt: skip
        try:
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
    run commands, test a task's branch). It is reset to the default branch at every run
    and never pushed: real changes go through tasks. Expects the repository synced."""
    ref = f"refs/remotes/origin/{project.default_branch}"
    path = desk_dir(project, employee)
    async with _repo_locks[project.id]:
        if not (path / ".git").exists():
            await _clone_from_reference(project, path)
        else:
            await _pull_from_reference(project, path)
        await git(path, "checkout", "--quiet", "--force", "--detach", ref)
        await git(path, "clean", "--quiet", "-fdx")
    return path


async def remove_task_worktree(project: Project, task: Task) -> None:
    """A merged task's clone is of no use any more, and its branch went with it."""
    path = project_dir(project) / "worktrees" / f"task-{task.id}"
    async with _repo_locks[project.id]:
        await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
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
            if await _has_ref(path, f"refs/remotes/origin/{branch}"):
                await git(path, "checkout", "--quiet", "-B", branch, "--track", f"origin/{branch}")
            else:
                await git(path, "checkout", "--quiet", "-b", branch, f"origin/{project.default_branch}")
        except GitHubError:
            await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
            raise
    return branch, path
