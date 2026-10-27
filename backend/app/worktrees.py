"""Local clone of each project's repository, and one git worktree per task."""

import asyncio
import re
from collections import defaultdict
from pathlib import Path

from app.config import settings
from app.github import GitHubError, git
from app.models import Project, Task


# One git operation at a time on a project's main clone (clone, fetch, worktree add)
_repo_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def project_dir(project: Project) -> Path:
    return settings.projects_dir / f"project-{project.id}"


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
    await git(repo, "checkout", "--quiet", "--force", "--detach", f"origin/{project.default_branch}")
    return repo


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
