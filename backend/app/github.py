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
BRANCH_PATTERN = r"^(?!-)(?!.*\.\.)[\w./-]{1,200}(?<![/.])\Z"
# A task's own branch: the legacy `task/<id>...` or `<type>/<id>-<slug>`, type as in Conventional Commits
TASK_BRANCH_RE = re.compile(
    r"(task|feat|fix|chore|docs|refactor|test|ci|perf|build|style|revert)/\d+(-[a-z0-9]+)*"
)


def is_task_branch_name(branch: str | None) -> bool:
    return bool(branch) and TASK_BRANCH_RE.fullmatch(branch) is not None


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


# Agents can write the repo config and hooks: never let them run code, least of all with the token
# Only https, and no credential helper: the repo config cannot make git run a command during a fetch/push
SAFE_GIT_CONFIG = (
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "protocol.allow=never",
    "-c", "protocol.https.allow=always",
    "-c", "credential.helper=",
    "-c", "core.askPass=",
)  # fmt: skip
# The backend's own secrets (GITHUB_TOKEN, ADMIN_TOKEN, DATABASE_URL...) must not reach git children
ENV_ALLOWLIST = (
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy",
)  # fmt: skip
NETWORK_COMMANDS = {"clone", "fetch", "push", "pull", "ls-remote"}


def _git_env(repo_url: str | None, allow_file: bool = False) -> dict[str, str]:
    # No system config: only the repo's own config remains, neutralised by SAFE_GIT_CONFIG
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    # GIT_ALLOW_PROTOCOL beats every `protocol.<name>.allow` of the repo config (ext::, file...)
    env |= {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ALLOW_PROTOCOL": "https:file" if allow_file else "https",
        # The env beats `core.askPass`: a 401 must never run a program from the repo config
        # with the token in its environment
        "GIT_ASKPASS": "/bin/true",
        "SSH_ASKPASS": "/bin/true",
    }
    if repo_url and repo_url.startswith("https://") and settings.github_token:
        # Passed through the environment so the token never shows up in the process list
        basic = base64.b64encode(f"x-access-token:{settings.github_token}".encode()).decode()
        env |= {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        }
    return env


async def git(
    cwd: str | Path, *args: str, repo_url: str | None = None, allow_file: bool = False,
    trust: str | Path | None = None,
) -> str:
    """allow_file: let this one call use the local `file` transport (a clone or a fetch between
    the reference and an agent clone); every other call stays https only. repo_url (the token) is
    only ever given for a repository whose config the backend alone writes, never an agent clone.
    trust: another repository the command reads from, owned by the agent's user."""
    # The token only goes to network commands
    network = bool(args) and args[0] in NETWORK_COMMANDS
    # Agent clones may belong to another user (isolation, #101): the backend still reads and updates them
    config = ["-c", f"safe.directory={cwd}"]
    if trust:
        config += ["-c", f"safe.directory={trust}"]
    if allow_file:
        config += ["-c", "protocol.file.allow=always"]
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(cwd), *SAFE_GIT_CONFIG, *config, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_git_env(repo_url if network else None, allow_file),
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


async def production_branch(repo: str) -> str:
    """The repository's default branch as GitHub declares it. Failing that, `main`, then
    `master` if only that one exists; `main` for a repository that has nothing yet."""
    declared = (await _api("GET", f"/repos/{repo}")).get("default_branch")
    if declared:
        return declared
    if await has_commits(repo) and not await branch_exists(repo, "main") and await branch_exists(repo, "master"):
        return "master"
    return "main"


async def resolve_branch(repo: str, branch: str) -> str:
    """The branch a project works from: `branch` if given, else the repository's default
    branch. A repository without commits accepts any: the first commit creates it."""
    default = await production_branch(repo)
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
    ref = await _api("GET", f"/repos/{repo}/git/ref/heads/{quote(from_branch, safe='/')}")
    await _api("POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": ref["object"]["sha"]})


async def set_pull_request_base(repo: str, number: int, base: str) -> None:
    await _api("PATCH", f"/repos/{repo}/pulls/{number}", json={"base": base})


async def set_pull_request_title(repo: str, number: int, title: str) -> None:
    await _api("PATCH", f"/repos/{repo}/pulls/{number}", json={"title": title})


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


async def merge_pull_request(repo: str, number: int, title: str, method: str = "squash", sha: str | None = None) -> None:
    """With `sha`, GitHub refuses (409) if the PR's head has moved since it was checked."""
    body = {"merge_method": method, "commit_title": title}
    if sha:
        body["sha"] = sha
    await _api("PUT", f"/repos/{repo}/pulls/{number}/merge", json=body)


async def find_pull_request(repo: str, head: str, base: str) -> dict | None:
    """The open PR from `head` to `base`, if there is one."""
    owner = repo.split("/")[0]
    pulls = await _api("GET", f"/repos/{repo}/pulls", params={"head": f"{owner}:{head}", "base": base, "state": "open"})
    return pulls[0] if pulls else None


async def list_pull_requests(repo: str) -> list[dict]:
    """The repository's open PRs, newest first (at most 100)."""
    return await _api("GET", f"/repos/{repo}/pulls", params={"state": "open", "per_page": 100})


async def get_pull_request(repo: str, number: int) -> dict:
    return await _api("GET", f"/repos/{repo}/pulls/{number}")


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
    return await commit_checks(repo, pr["head"]["sha"])


async def commit_checks(repo: str, sha: str) -> str | None:
    """None if CI passed on the commit, otherwise the reason it did not."""
    runs = (await _api("GET", f"/repos/{repo}/commits/{sha}/check-runs"))["check_runs"]
    if not runs:
        return "no CI checks reported"
    if pending := [r["name"] for r in runs if r["status"] != "completed"]:
        return f"CI still running: {', '.join(pending)}"
    if failed := [r["name"] for r in runs if r["conclusion"] not in OK_CONCLUSIONS]:
        return f"CI failed: {', '.join(failed)}"
    return None


async def file_content(repo: str, path: str, ref: str) -> str | None:
    """A text file of the repository at `ref`; None if it does not exist there."""
    try:
        data = await _api("GET", f"/repos/{repo}/contents/{quote(path, safe='/')}", params={"ref": ref})
    except GitHubError as exc:
        if " 404 " not in str(exc):
            raise
        return None
    return base64.b64decode(data["content"]).decode(errors="replace")


async def tag_exists(repo: str, tag: str) -> bool:
    try:
        await _api("GET", f"/repos/{repo}/git/ref/tags/{quote(tag, safe='')}")
    except GitHubError as exc:
        if " 404 " not in str(exc):
            raise
        return False
    return True


async def branch_head(repo: str, branch: str) -> str:
    """The commit SHA at the tip of a branch."""
    return (await _api("GET", f"/repos/{repo}/branches/{quote(branch, safe='')}"))["commit"]["sha"]


def release_name(tag: str) -> str:
    """The title of a release, as release.yml and the hand-made releases wrote it."""
    return f"Palabre {tag}"


COMMIT_TITLE_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<desc>.+)$")
VERSION_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
# Section titles in release order; every type not listed goes to Other
CHANGE_SECTIONS = {"feat": "Features", "fix": "Bug Fixes", "perf": "Performance", "docs": "Documentation"}
OTHER_SECTION = "Other"


def release_changes(commits: list[str]) -> str:
    """The changes of a version as Markdown, one line per commit message, grouped by Conventional
    Commits type. Messages that do not follow the format (old commits) go to Other."""
    groups: dict[str, list[str]] = {}
    breaking: list[str] = []
    for message in commits:
        title, _, body = message.strip().partition("\n")
        match = COMMIT_TITLE_RE.match(title.strip())
        if not match:
            groups.setdefault(OTHER_SECTION, []).append(title.strip())
            continue
        line = f"{match['scope']}: {match['desc']}" if match["scope"] else match["desc"]
        groups.setdefault(CHANGE_SECTIONS.get(match["type"], OTHER_SECTION), []).append(line)
        if match["bang"] or "BREAKING CHANGE" in body:
            breaking.append(line)
    sections = [("Breaking Changes", breaking)] + [(name, groups.get(name, [])) for name in [*CHANGE_SECTIONS.values(), OTHER_SECTION]]
    return "\n\n".join(f"### {name}\n" + "\n".join(f"- {line}" for line in lines) for name, lines in sections if lines)


def previous_tag(tags: list[str], tag: str) -> str | None:
    """The highest vX.Y.Z tag below `tag`, if any."""
    def key(name: str) -> tuple[int, ...]:
        return tuple(int(n) for n in VERSION_TAG_RE.match(name).groups())

    versions = [name for name in tags if VERSION_TAG_RE.match(name)]
    older = [name for name in versions if name != tag and (not VERSION_TAG_RE.match(tag) or key(name) < key(tag))]
    return max(older, key=key, default=None)


async def release_commits(repo: str, tag: str, head: str) -> list[str]:
    """Messages of the commits between the tag before `tag` and `head` (all of them for a first release).
    Merge commits are left out: they only carry the release PR's own title."""
    tags = [t["name"] for t in await _api("GET", f"/repos/{repo}/tags", params={"per_page": 100})]
    base = previous_tag(tags, tag)
    if base:
        data = await _api("GET", f"/repos/{repo}/compare/{quote(base, safe='')}...{quote(head, safe='')}")
        commits = data["commits"]
    else:
        commits = await _api("GET", f"/repos/{repo}/commits", params={"sha": head, "per_page": 100})
    return [c["commit"]["message"] for c in reversed(commits) if len(c.get("parents", [])) < 2]


def release_notes(repo: str, tag: str, changes: str = "") -> str:
    """The body of a release: the changes, then the same download text as release.yml (keep both in step)."""
    owner = repo.split("/")[0].lower()
    download = "\n".join([
        "Desktop app: download the file for your system below.",
        "- macOS: `.dmg` (aarch64 = Apple Silicon, x64 = Intel). The app is not signed: the first time, right-click it → Open, or run `xattr -dr com.apple.quarantine /Applications/Palabre.app`.",
        "- Windows: `.msi` or `-setup.exe`.",
        "- Linux: `.AppImage`, `.deb` or `.rpm`.",
        "",
        f"Server: `ghcr.io/{owner}/palabre:{tag.removeprefix('v')}` (see the README).",
    ])  # fmt: skip
    return f"{changes}\n\n{download}" if changes else download


async def _notes_with_changes(repo: str, tag: str, head: str) -> str:
    return release_notes(repo, tag, release_changes(await release_commits(repo, tag, head)))


async def create_release(repo: str, tag: str, sha: str) -> dict:
    """Tag `sha` and publish the GitHub Release for it, in one call. The tag push starts release.yml."""
    return await _api(
        "POST",
        f"/repos/{repo}/releases",
        json={"tag_name": tag, "target_commitish": sha, "name": release_name(tag), "body": await _notes_with_changes(repo, tag, sha)},
    )


async def update_release(repo: str, tag: str) -> dict:
    """Reset the name and notes of the existing release of `tag` to the standard ones, changes included."""
    release = await _api("GET", f"/repos/{repo}/releases/tags/{quote(tag, safe='')}")
    return await _api(
        "PATCH",
        f"/repos/{repo}/releases/{release['id']}",
        json={"name": release_name(tag), "body": await _notes_with_changes(repo, tag, tag)},
    )


def latest_tag(tags: list[str]) -> str | None:
    """The highest vX.Y.Z tag, if any."""
    versions = [name for name in tags if VERSION_TAG_RE.match(name)]
    return max(versions, key=lambda name: tuple(int(n) for n in VERSION_TAG_RE.match(name).groups()), default=None)


async def latest_version_tag(repo: str) -> str | None:
    return latest_tag([t["name"] for t in await _api("GET", f"/repos/{repo}/tags", params={"per_page": 100})])


async def compare_commits(repo: str, base: str, head: str) -> tuple[int, list[str]]:
    """(commits of `head` that `base` lacks, their messages without merge commits), oldest first."""
    data = await _api("GET", f"/repos/{repo}/compare/{quote(base, safe='')}...{quote(head, safe='')}")
    messages = [c["commit"]["message"] for c in data["commits"] if len(c.get("parents", [])) < 2]
    return data["ahead_by"], messages


async def branch_tip(repo: str, branch: str) -> dict:
    """The tip of a branch: its SHA, the message and the date of its commit."""
    data = (await _api("GET", f"/repos/{repo}/branches/{quote(branch, safe='')}"))["commit"]
    return {"sha": data["sha"], "message": data["commit"]["message"], "date": data["commit"]["committer"]["date"]}


async def commit_files(repo: str, branch: str, parent: str, files: dict[str, str], message: str) -> str:
    """One commit on `branch` changing `files` (path to new text), on top of `parent`, which must still
    be the branch's tip: the update is refused otherwise (no force). Returns the new SHA."""
    base = await _api("GET", f"/repos/{repo}/git/commits/{parent}")
    tree = await _api(
        "POST",
        f"/repos/{repo}/git/trees",
        json={"base_tree": base["tree"]["sha"], "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files.items()]},
    )
    commit = await _api("POST", f"/repos/{repo}/git/commits", json={"message": message, "tree": tree["sha"], "parents": [parent]})
    await _api("PATCH", f"/repos/{repo}/git/refs/heads/{quote(branch, safe='/')}", json={"sha": commit["sha"], "force": False})
    return commit["sha"]
