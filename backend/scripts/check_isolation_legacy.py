"""Legacy shared-account mode (agent_pool_size 0) inside the real image: run by check-isolation.sh as the palabre user (#194).

The clone is built by the real worktrees._clone_from_reference (palabre:palabre, root closed to 0700), then read the way
push_task_branch reads it: through the sudo rule, as the shared `agent`. Needs no GitHub access.
Prints `ok   ...` / `FAIL ...` lines; exit code 1 on any FAIL.
"""

import asyncio
import subprocess
import tempfile
from pathlib import Path

from app import github, worktrees
from app.config import settings
from app.github import GitHubError
from app.models import Project

failed = False
PROJECT_ID = 99995


def report(ok: bool, desc: str, got: object = None) -> None:
    global failed
    failed |= not ok
    print(f"{'ok  ' if ok else 'FAIL'} {desc}", flush=True)
    if not ok:
        print(f"::error::{desc}" + (f": got {got!r}" if got is not None else ""), flush=True)


def run_git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


async def fetch_as_agent(clone: Path, scratch: Path) -> str | None:
    """The fetch of push_task_branch (keep in sync), with the upload-pack it picks in legacy mode; the error, or None."""
    try:
        user = worktrees._clone_owner_account(clone)
        if user:
            worktrees._require_sudo_upload_pack()
        await worktrees._require_isolated_clone(clone)
        await github.git(
            scratch, "fetch", "--quiet", "--no-tags", f"--upload-pack={github.upload_pack_command(clone, user)}",
            str(clone), "+refs/heads/task/1:refs/heads/task/1",
            allow_file=True, trust=clone / ".git", config=("transfer.fsckObjects=true",),
        )  # fmt: skip
    except GitHubError as exc:
        return str(exc)
    return None


def new_scratch() -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="legacy-"))
    run_git(scratch, "init", "-q")
    return scratch


async def main() -> None:
    saved = settings.agent_user, settings.agent_pool_size
    settings.agent_user, settings.agent_pool_size = "agent", 0
    project = Project(id=PROJECT_ID, name="legacy", repo_url="https://example.invalid/legacy.git", default_branch="main")
    reference = worktrees.repo_dir(project)
    clone = worktrees.project_dir(project) / "worktrees" / "task-1"
    scratches: list[Path] = []
    try:
        reference.mkdir(parents=True)
        reference.chmod(0o700)  # As _sync_repo leaves it
        run_git(reference, "init", "-q")
        run_git(reference, "commit", "-q", "--allow-empty", "-m", "base")
        run_git(reference, "update-ref", "refs/remotes/origin/main", "HEAD")
        await worktrees._clone_from_reference(project, clone)
        run_git(clone, "checkout", "-q", "-b", "task/1")
        run_git(clone, "commit", "-q", "--allow-empty", "-m", "legacy")
        sha = run_git(clone, "rev-parse", "HEAD")
        scratches.append(scratch := new_scratch())
        report(worktrees._clone_owner_account(clone) == "agent", "legacy mode serves the clone as the shared agent account")
        error = await fetch_as_agent(clone, scratch)
        report(error is None, "the upload-pack as agent serves a legacy clone built by the backend", error)
        report(subprocess.run(["git", "-C", str(scratch), "cat-file", "-e", sha]).returncode == 0, "the legacy commit reached the scratch repo")
        # Negative control: with the objects closed to group and other, the same fetch must fail
        subprocess.run(["chmod", "-R", "go-rwx", str(clone / ".git" / "objects")], check=True)
        scratches.append(closed := new_scratch())
        error = await fetch_as_agent(clone, closed)
        report(error is not None, "agent cannot be served a clone whose objects are closed to group and other")
    finally:
        settings.agent_user, settings.agent_pool_size = saved
        await worktrees.remove_project_files(PROJECT_ID)
        for scratch in scratches:
            subprocess.run(["rm", "-rf", str(scratch)])


asyncio.run(main())
