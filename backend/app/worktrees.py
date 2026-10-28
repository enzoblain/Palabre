"""Local clone of each project's repository, and one git worktree per task."""

import asyncio
import os
import re
import shutil
from collections import defaultdict
from pathlib import Path

from app.config import settings
from app.github import GitHubError, git
from app.models import Employee, Project, Task


# One git operation at a time on a project's main clone (clone, fetch, worktree add)
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
    """Everything a project left on disk: clone, task worktrees, desks, and the agents'
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


async def _initial_commit(project: Project, repo: Path) -> None:
    """A brand-new GitHub repository has no commit: tasks need a default branch to start
    from, so an empty first commit is pushed."""
    branch = project.default_branch
    # Already made by an attempt whose push failed: only the push is left
    if not await _has_ref(repo, f"refs/heads/{branch}"):
        await git(repo, "checkout", "--quiet", "--orphan", branch)
        await git(
            repo, "-c", "user.name=Palabre", "-c", "user.email=palabre@palabre.local",
            "commit", "--quiet", "--allow-empty", "-m", "Initial commit",
        )  # fmt: skip
    await git(repo, "push", "--quiet", "origin", f"refs/heads/{branch}:refs/heads/{branch}", repo_url=project.repo_url)
    await git(repo, "fetch", "--quiet", "origin", repo_url=project.repo_url)


def desk_dir(project: Project, employee: Employee) -> Path:
    return project_dir(project) / "desks" / f"employee-{employee.id}"


async def prepare_desk(project: Project, employee: Employee) -> Path:
    """The employee's own scratch checkout, where they work during conversations (read,
    run commands, test a task's branch). It is reset to the default branch at every run
    and never pushed: real changes go through tasks. Expects the repository synced."""
    ref = f"refs/remotes/origin/{project.default_branch}"
    path = desk_dir(project, employee)
    async with _repo_locks[project.id]:
        if not (path / ".git").exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            await git(repo_dir(project), "worktree", "prune")
            await git(repo_dir(project), "worktree", "add", "--quiet", "--detach", str(path), ref)
        else:
            await git(path, "checkout", "--quiet", "--force", "--detach", ref)
            await git(path, "clean", "--quiet", "-fdx")
    return path


def branch_name(task: Task) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task.title.lower()).strip("-")[:40].rstrip("-") or "task"
    return f"task/{task.id}-{slug}"


async def prepare_worktree(project: Project, task: Task) -> tuple[str, Path]:
    """The task's branch and worktree, created from the default branch on first use.
    An existing worktree is kept as is: it holds the assignee's work in progress."""
    branch = task.branch or branch_name(task)
    path = project_dir(project) / "worktrees" / f"task-{task.id}"
    if path.exists():
        return branch, path

    async with _repo_locks[project.id]:
        repo = await _sync_repo(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
            await git(repo, "worktree", "add", "--quiet", str(path), branch)
        except GitHubError:
            await git(
                repo, "worktree", "add", "--quiet", "-b", branch, str(path), f"origin/{project.default_branch}"
            )
    return branch, path
