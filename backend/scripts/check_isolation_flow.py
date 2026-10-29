"""Agent runs and task flow inside the real image: run by check-isolation.sh as the palabre user.

The `claude` binary is replaced by a stub (see check-isolation.sh), so the runs go through the
real runner (sudo -u agent, environment, process group, kill) without a Claude account.
Prints `ok   ...` / `FAIL ...` / `SKIP ...` lines; exit code 1 on any FAIL.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from app import runner, toolchains, worktrees
from app.config import settings
from app.github import GitHubError, delete_branch, merge_pull_request, open_pull_request, repo_slug
from app.github import is_pull_request_open
from app.runner import ClaudeRunError, RunSpec

failed = False
PROJECT_ID = 99999


def report(ok: bool, desc: str) -> None:
    global failed
    failed |= not ok
    print(f"{'ok  ' if ok else 'FAIL'} {desc}", flush=True)


def spec(prompt: str, cwd: Path) -> RunSpec:
    return RunSpec(
        author_name="Check Bot", system_prompt="x", prompt=prompt, cwd=cwd, employee_id=0,
        mcp_headers={}, mcp_tools=[], claude_tools=["Read"], model="x", oauth_token="check-token",
    )  # fmt: skip


def parse(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def agent_processes() -> list[str]:
    out = subprocess.run(["pgrep", "-u", settings.agent_user, "-a"], capture_output=True, text=True)
    return out.stdout.splitlines()


async def probe(cwd: Path, reference: Path) -> None:
    """A run as the agent tries to reach what the backend keeps for itself."""
    pids = [os.getpid()] + [int(p) for p in subprocess.run(
        ["pgrep", "-u", "palabre", "-f", "uvicorn"], capture_output=True, text=True).stdout.split()]  # fmt: skip
    result = await runner.run_claude(spec(f"probe {cwd} {reference} {' '.join(map(str, pids))}", cwd))
    got = parse(result.text)
    report(got.get("uid") == "1001", f"the run is uid agent (got uid={got.get('uid')}) via sudo -u")
    expected = f"{toolchains.bin_dir()}:/usr/local/bin:/usr/bin:/bin"
    report(got.get("path") == expected, f"the run's PATH is the toolchains + system PATH (got {got.get('path')})")
    report(got.get("home") == "/home/agent", f"the run's HOME is the agent's (got {got.get('home')})")
    report(got.get("secrets") == "0", "no backend secret in the run's environment")
    report(got.get("environ") == "denied", "the run cannot read /proc/<backend pid>/environ")
    report(got.get("reference") == "denied", "the run cannot read the project reference")
    report(got.get("runtime") == "denied", "the run cannot list /data/runtime")
    report(got.get("secretsdir") == "denied", "the run cannot read the backend's secret files")
    report(got.get("mcpconfig") == "ok", "the run can read its MCP config in /data/run")
    report(got.get("cwdwrite") == "ok", "the run can write in its own clone")


async def timeout_run(cwd: Path) -> None:
    settings.agent_timeout_s = 3
    try:
        await runner.run_claude(spec("hang", cwd))
        report(False, "a run past the timeout is stopped")
    except ClaudeRunError as exc:
        report("Timed out" in str(exc), "a run past the timeout is stopped")
    await asyncio.sleep(1)
    left = agent_processes()
    report(not left, f"no process of the agent is left after the timeout kill ({'; '.join(left) or 'none'})")


async def flow(repo: str, branch: str) -> None:
    project = SimpleNamespace(id=PROJECT_ID, repo_url=f"https://github.com/{repo}", default_branch=branch)
    task = SimpleNamespace(id=PROJECT_ID, branch=None, worktree_path=None)
    pr = None
    try:
        task.branch, path = await worktrees.prepare_worktree(project, task)
        task.worktree_path = str(path)
        report(path.is_dir(), f"the task clone is created ({path})")
        await probe(path, worktrees.repo_dir(project))
        await timeout_run(path)

        result = await runner.run_claude(spec(f"commit {path}", path))
        report(parse(result.text).get("commit") == "ok", "the agent commits in its clone")
        report(
            "x-access-token" not in (path / ".git" / "config").read_text(), "the agent clone holds no GitHub token"
        )

        await worktrees.push_task_branch(project, task)
        report(True, f"the branch {task.branch} is pushed from the reference")

        title = "test(isolation): end-to-end check, safe to delete"
        pr = await open_pull_request(repo, task.branch, branch, title, "Opened by check-isolation.sh")
        await merge_pull_request(repo, pr["number"], title)
        report(not await is_pull_request_open(repo, pr["number"]), f"the pull request #{pr['number']} is merged")
    except (GitHubError, ClaudeRunError, OSError) as exc:
        report(False, f"flow stopped: {exc}")
    finally:
        if task.branch:
            await delete_branch(repo, task.branch)
        await worktrees.remove_project_files(project.id)


async def main() -> None:
    report(settings.agent_user == "agent", f"AGENT_USER is set in the image (got {settings.agent_user!r})")
    repo = os.environ.get("CHECK_GITHUB_REPO")
    if repo:
        repo_slug(f"https://github.com/{repo}")  # Fails early on a malformed name
        await flow(repo, os.environ.get("CHECK_BRANCH", "main"))
        return
    print("SKIP the task flow (clone, commit, push, merge) and the reference checks: set CHECK_GITHUB_REPO")
    # Runs from a scratch directory the agent can write in
    scratch = settings.projects_dir / f"project-{PROJECT_ID}" / "worktrees" / "scratch"
    scratch.mkdir(mode=0o2775, parents=True, exist_ok=True)
    scratch.chmod(0o2775)
    reference = scratch.parent.parent / "repo"  # Stands for a project's reference clone
    reference.mkdir(mode=0o700, exist_ok=True)
    (reference / "config").write_text("[remote]\n")
    reference.chmod(0o700)
    try:
        await probe(scratch, reference)
        await timeout_run(scratch)
    finally:
        await worktrees.remove_project_files(PROJECT_ID)
    global failed
    failed = True  # An incomplete check is not a pass


asyncio.run(main())
sys.exit(1 if failed else 0)
