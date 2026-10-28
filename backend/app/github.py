"""Git and GitHub operations. Only the backend runs these: agents never get the token."""

import asyncio
import base64
import os
import re
from pathlib import Path
from urllib.parse import quote

import httpx

from app.config import settings

API_URL = "https://api.github.com"
REPO_URL_RE = re.compile(r"^(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?/?$")
OK_CONCLUSIONS = {"success", "neutral", "skipped"}
# A branch name we accept: no spaces, "..", leading "-" or trailing "/" or "."
BRANCH_PATTERN = r"^(?!-)(?!.*\.\.)[\w./-]{1,200}(?<![/.])$"


class GitHubError(RuntimeError):
    pass


def repo_slug(repo_url: str) -> str:
    """`https://github.com/owner/repo(.git)` or `git@github.com:owner/repo.git` → `owner/repo`."""
    match = REPO_URL_RE.match(repo_url)
    if match is None:
        raise GitHubError(f"Not a GitHub repository URL: {repo_url}")
    return match.group(1)


def https_url(repo_url: str) -> str:
    """The HTTPS URL of a GitHub repository: the one git uses, with the token (the server
    has no SSH key, so `git@github.com:` URLs cannot be cloned as they are)."""
    return f"https://github.com/{repo_slug(repo_url)}"


def _git_env(repo_url: str | None) -> dict[str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if repo_url and repo_url.startswith("https://") and settings.github_token:
        # Passed through the environment so the token never shows up in the process list
        basic = base64.b64encode(f"x-access-token:{settings.github_token}".encode()).decode()
        env |= {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        }
    return env


async def git(cwd: str | Path, *args: str, repo_url: str | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(cwd), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_git_env(repo_url),
    )  # fmt: skip
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise GitHubError(f"git {args[0]} failed: {stderr.decode(errors='replace')[-1000:]}")
    return stdout.decode(errors="replace")


async def _api(method: str, path: str, **kwargs) -> dict:
    if not settings.github_token:
        raise GitHubError("GITHUB_TOKEN is not configured")
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(base_url=API_URL, headers=headers, timeout=30) as client:
        response = await client.request(method, path, **kwargs)
    if response.status_code >= 400:
        raise GitHubError(f"GitHub {method} {path}: {response.status_code} {response.text[:500]}")
    return response.json() if response.content else {}


WORKING_BRANCH = "dev"


async def has_commits(repo: str) -> bool:
    return bool(await _api("GET", f"/repos/{repo}/branches", params={"per_page": 1}))


async def resolve_branch(repo: str, branch: str) -> str:
    """The branch a project works from: `branch` if given, else the repository's default
    branch. A repository without commits accepts any: the first commit creates it."""
    default = (await _api("GET", f"/repos/{repo}"))["default_branch"]
    if not branch:
        return default
    if not await has_commits(repo):
        return branch
    if not await branch_exists(repo, branch):
        raise GitHubError(f"The branch '{branch}' does not exist on {repo} (its default branch is '{default}')")
    return branch


async def branch_exists(repo: str, branch: str) -> bool:
    try:
        await _api("GET", f"/repos/{repo}/branches/{quote(branch, safe='')}")
    except GitHubError as exc:
        if " 404 " not in str(exc):
            raise
        return False
    return True


async def create_branch(repo: str, branch: str, from_branch: str) -> None:
    ref = await _api("GET", f"/repos/{repo}/git/ref/heads/{from_branch}")
    await _api("POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": ref["object"]["sha"]})


async def set_pull_request_base(repo: str, number: int, base: str) -> None:
    await _api("PATCH", f"/repos/{repo}/pulls/{number}", json={"base": base})


async def open_pull_request(repo: str, head: str, base: str, title: str, body: str) -> dict:
    return await _api(
        "POST", f"/repos/{repo}/pulls", json={"head": head, "base": base, "title": title, "body": body}
    )


async def comment_pull_request(repo: str, number: int, body: str) -> None:
    await _api("POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body})


async def post_review(repo: str, number: int, body: str) -> None:
    # Always a COMMENT review: every PR is opened with the backend's token, and GitHub
    # forbids approving your own PR. Approvals are tracked in Palabre instead.
    await _api("POST", f"/repos/{repo}/pulls/{number}/reviews", json={"body": body, "event": "COMMENT"})


async def delete_branch(repo: str, branch: str) -> None:
    """Delete a branch on GitHub; already gone is fine."""
    try:
        await _api("DELETE", f"/repos/{repo}/git/refs/heads/{branch}")
    except GitHubError as exc:
        if " 422 " not in str(exc) and " 404 " not in str(exc):
            raise


async def merge_pull_request(repo: str, number: int, title: str, method: str = "squash") -> None:
    await _api(
        "PUT",
        f"/repos/{repo}/pulls/{number}/merge",
        json={"merge_method": method, "commit_title": title},
    )


async def find_pull_request(repo: str, head: str, base: str) -> dict | None:
    """The open PR from `head` to `base`, if there is one."""
    owner = repo.split("/")[0]
    pulls = await _api("GET", f"/repos/{repo}/pulls", params={"head": f"{owner}:{head}", "base": base, "state": "open"})
    return pulls[0] if pulls else None


async def close_pull_request(repo: str, number: int) -> None:
    await _api("PATCH", f"/repos/{repo}/pulls/{number}", json={"state": "closed"})


async def is_pull_request_open(repo: str, number: int) -> bool:
    """Whether the PR is still open; a PR that no longer exists is not."""
    try:
        return (await _api("GET", f"/repos/{repo}/pulls/{number}"))["state"] == "open"
    except GitHubError as exc:
        if " 404 " not in str(exc):
            raise
        return False


async def checks_status(repo: str, number: int) -> str | None:
    """None if CI passed on the PR's head commit, otherwise the reason it did not."""
    pr = await _api("GET", f"/repos/{repo}/pulls/{number}")
    runs = (await _api("GET", f"/repos/{repo}/commits/{pr['head']['sha']}/check-runs"))["check_runs"]
    if not runs:
        return "no CI checks reported"
    if pending := [r["name"] for r in runs if r["status"] != "completed"]:
        return f"CI still running: {', '.join(pending)}"
    if failed := [r["name"] for r in runs if r["conclusion"] not in OK_CONCLUSIONS]:
        return f"CI failed: {', '.join(failed)}"
    return None
