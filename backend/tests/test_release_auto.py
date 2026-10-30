"""Automatic releases: SemVer bump, files and CHANGELOG, the pending-release watchdog, the publish hint."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import github, projects, release, worktrees
from app.orchestrator import merge_watch
from app.services import WorkflowError

from .conftest import make_project
from .test_merge_watch import WatchSession, events_of
from .test_release_shipping import FakeSession, versioned

CHANGELOG = """# Changelog

## [Unreleased]

## [0.6.1] - 2026-10-29

### Fixed

- Something.

[Unreleased]: https://github.com/acme/app/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/acme/app/compare/v0.6.0...v0.6.1
"""
LOCK = '{\n  "name": "x",\n  "version": "0.6.1",\n  "packages": {\n    "": {\n      "name": "x",\n      "version": "0.6.1",\n      "dependencies": {\n        "a": "1.0.0"\n      }\n    },\n    "node_modules/a": {\n      "version": "1.0.0"\n    }\n  }\n}\n'
CARGO_LOCK = '[[package]]\nname = "a"\nversion = "1.0.0"\n\n[[package]]\nname = "x"\nversion = "0.6.1"\n'


@pytest.mark.parametrize(
    ("current", "commits", "expected"),
    [
        ("0.6.1", ["fix(a): b"], "0.6.2"),
        ("0.6.1", ["perf: faster"], "0.6.2"),
        ("0.6.1", ["fix: b", "feat(a): c"], "0.7.0"),
        ("0.6.1", ["feat!: gone"], "0.7.0"),
        ("1.2.3", ["feat!: gone"], "2.0.0"),
        ("1.2.3", ["fix: x\n\nBREAKING CHANGE: y"], "2.0.0"),
        ("1.2.3", ["chore: a", "docs: b", "chore(release): 1.2.3"], None),
        ("1.2.3", ["not conventional"], None),
    ],
)
def test_next_version(current, commits, expected):
    assert release.next_version(current, commits) == expected


def test_changelog_entry_and_links():
    entry = release.changelog_entry("0.7.0", "2026-11-01", ["feat(api): add x", "fix: y", "chore: z", "refactor!: w"])
    assert entry.startswith("## [0.7.0] - 2026-11-01\n\n### Added\n\n- api: add x")
    assert "### Fixed\n\n- y" in entry and "**Breaking:** w" in entry and "chore" not in entry
    text = release.update_changelog(CHANGELOG, "0.7.0", "0.6.1", entry)
    assert text.index("## [0.7.0]") < text.index("## [0.6.1]")
    assert "[Unreleased]: https://github.com/acme/app/compare/v0.7.0...HEAD\n[0.7.0]: https://github.com/acme/app/compare/v0.6.1...v0.7.0\n[0.6.1]" in text


def test_update_changelog_replaces_a_hand_written_unreleased_and_a_stale_entry():
    text = CHANGELOG.replace(
        "## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- Written by hand.\n\n## [0.6.5] - 2026-10-30\n\n### Fixed\n\n- Never released.\n"
    ) + "[0.6.5]: https://github.com/acme/app/compare/v0.6.1...v0.6.5\n"
    entry = release.changelog_entry("0.7.0", "2026-11-01", ["feat: add x", "feat: add z"])
    out = release.update_changelog(text, "0.7.0", "0.6.1", entry)
    assert out.count("### Added") == 1 and "by hand" not in out and "0.6.5" not in out
    assert "- add x\n- add z" in out and "## [0.6.1]" in out and "[0.7.0]: " in out


def test_set_version_touches_only_the_package_version():
    lock = json.loads(release.set_version("frontend/package-lock.json", LOCK, "0.7.0"))
    assert lock["version"] == lock["packages"][""]["version"] == "0.7.0"
    assert lock["packages"]["node_modules/a"]["version"] == "1.0.0"
    cargo = release.set_version("frontend/src-tauri/Cargo.lock", CARGO_LOCK, "0.7.0", "x")
    assert 'name = "a"\nversion = "1.0.0"' in cargo and 'name = "x"\nversion = "0.7.0"' in cargo
    assert 'version = "0.7.0"' in release.set_version("frontend/src-tauri/Cargo.toml", versioned("0.6.1")["frontend/src-tauri/Cargo.toml"], "0.7.0")


def indented(version):
    """versioned() as npm and Tauri write it: indented JSON."""
    files = versioned(version)
    for path in ("frontend/package.json", "frontend/src-tauri/tauri.conf.json"):
        files[path] = json.dumps(json.loads(files[path]), indent=2) + "\n"
    return files


def bumped(version):
    return indented(version) | {
        "frontend/package-lock.json": LOCK.replace("0.6.1", version),
        "frontend/src-tauri/Cargo.lock": CARGO_LOCK.replace("0.6.1", version),
    }


PROJECT = SimpleNamespace(id=1, repo_url="https://github.com/acme/app", default_branch="dev")


@pytest.fixture
def gh(monkeypatch):
    state = SimpleNamespace(
        commits=["fix: a", "feat(b): c"], ahead=2, files={}, pushed=None, tip_message="feat: c", tip_date=datetime.now(UTC) - timedelta(hours=1),
        pr=None, ci="CI still running: tests",
    )  # fmt: skip
    state.files = indented("0.6.1") | {"CHANGELOG.md": CHANGELOG, "frontend/package-lock.json": LOCK, "frontend/src-tauri/Cargo.lock": CARGO_LOCK}

    async def resolve_branch(repo, branch):
        return "main"

    async def latest_version_tag(repo):
        return "v0.6.1"

    async def compare_commits(repo, base, head):
        return (state.ahead, state.commits) if base == "main" else (len(state.commits), state.commits)

    async def branch_tip(repo, branch):
        return {"sha": "tip1", "message": state.tip_message, "date": state.tip_date.isoformat().replace("+00:00", "Z")}

    async def file_content(repo, path, ref):
        return state.files.get(path)

    async def commit_release(project, parent, files, message):
        state.pushed = (project.default_branch, parent, files, message)
        return "new1"

    async def find_pull_request(repo, head, base):
        return state.pr

    async def open_pull_request(repo, head, base, title, body):
        state.pr = {"number": 7, "html_url": "https://github.com/acme/app/pull/7", "head": {"sha": "new1"}}
        state.title = title
        return state.pr

    async def commit_checks(repo, sha):
        return state.ci

    for fn in (resolve_branch, latest_version_tag, compare_commits, branch_tip, file_content, find_pull_request, open_pull_request, commit_checks):
        monkeypatch.setattr(github, fn.__name__, fn)
    monkeypatch.setattr(worktrees, "commit_release", commit_release)
    return state


async def test_prepare_release_commits_files_and_changelog_in_one_commit(gh):
    result = await projects.prepare_release(PROJECT)
    branch, parent, files, message = gh.pushed
    assert (branch, parent, message) == ("dev", "tip1", "chore(release): 0.7.0")
    assert set(files) == {
        "frontend/package.json", "frontend/src-tauri/tauri.conf.json", "frontend/src-tauri/Cargo.toml",
        "frontend/package-lock.json", "frontend/src-tauri/Cargo.lock", "CHANGELOG.md",
    }
    assert json.loads(files["frontend/package.json"])["version"] == "0.7.0"
    assert "## [0.7.0]" in files["CHANGELOG.md"] and "- b: c" in files["CHANGELOG.md"]
    assert result["committed"] and result["version"] == "0.7.0" and result["sha"] == "new1"


async def test_prepare_release_does_nothing_when_files_are_up_to_date(gh):
    await projects.prepare_release(PROJECT)
    gh.files |= gh.pushed[2]
    gh.pushed = None
    result = await projects.prepare_release(PROJECT)
    assert gh.pushed is None and not result["committed"] and result["version"] == "0.7.0"


async def test_prepare_release_adds_a_commit_merged_after_the_bump(gh):
    await projects.prepare_release(PROJECT)
    gh.files |= gh.pushed[2]
    gh.commits = [*gh.commits, "fix(d): late fix", "chore(release): 0.7.0"]
    result = await projects.prepare_release(PROJECT)
    files = gh.pushed[2]
    assert result["committed"] and result["version"] == "0.7.0"
    assert "- d: late fix" in files["CHANGELOG.md"] and files["CHANGELOG.md"].count("## [0.7.0]") == 1
    assert set(files) == {"CHANGELOG.md"}  # The version files already hold 0.7.0


async def test_prepare_release_follows_a_higher_bump_level(gh):
    gh.commits = ["fix: a"]
    await projects.prepare_release(PROJECT)
    gh.files |= gh.pushed[2]
    assert "## [0.6.2]" in gh.files["CHANGELOG.md"]
    gh.commits = ["fix: a", "feat(e): late feature"]
    result = await projects.prepare_release(PROJECT)
    files = gh.pushed[2]
    assert result["version"] == "0.7.0" and json.loads(files["frontend/package.json"])["version"] == "0.7.0"
    assert "## [0.7.0]" in files["CHANGELOG.md"] and "0.6.2" not in files["CHANGELOG.md"]


def test_entry_date_reads_the_date_of_a_version():
    assert release.entry_date(CHANGELOG, "0.6.1") == "2026-10-29"
    assert release.entry_date(CHANGELOG, "0.9.9") is None


async def test_prepare_release_refuses_when_nothing_deserves_a_release(gh):
    gh.commits = ["chore: tidy", "docs: words"]
    with pytest.raises(WorkflowError, match="Nothing worth a release"):
        await projects.prepare_release(PROJECT)


async def test_merge_release_commits_the_bump_then_waits_for_the_new_ci(gh):
    with pytest.raises(WorkflowError, match="0.7.0 was committed.*PR #7"):
        await projects.merge_release(FakeSession(), PROJECT, "", "Notes")
    assert gh.pushed is not None and gh.title == "chore(release): 0.7.0"


async def test_merge_release_goes_on_once_the_bump_is_there(gh, monkeypatch):
    await projects.prepare_release(PROJECT)
    gh.files |= gh.pushed[2]
    gh.pr, gh.ci = {"number": 7, "html_url": "u", "head": {"sha": "new1"}}, None
    merged = []

    async def merge(repo, number, title, method="squash", sha=None):
        merged.append((number, sha, title))

    monkeypatch.setattr(github, "merge_pull_request", merge)
    assert await projects.merge_release(FakeSession(), PROJECT, "", "Notes") == ("u", 7)
    assert merged == [(7, "new1", "chore(release): 0.7.0")]


# --- watchdog ---------------------------------------------------------------------------


@pytest.fixture
def pending(gh, monkeypatch):
    monkeypatch.setattr(merge_watch, "_last_pending_check", {})
    monkeypatch.setattr(merge_watch, "team_conversation_id", lambda _s, _pid: _async(3))
    project = make_project()
    project.kind, project.default_branch, project.release_reminded_sha = "company", "dev", None
    return project


async def _async(value):
    return value


async def test_pending_release_wakes_the_lead_once_per_sha(pending, gh):
    s = WatchSession([pending], pending)  # No open task: scalar() answers None
    await merge_watch.watch_pending_release(s)
    merge_watch._last_pending_check.clear()
    await merge_watch.watch_pending_release(s)
    [event] = events_of(s, "release_pending")
    assert event.target_role == "lead" and event.payload["version"] == "0.7.0" and event.payload["count"] == 2
    assert "Features" not in event.payload["changes"] and "### Added" in event.payload["changes"]
    assert pending.release_reminded_sha == "tip1"


async def test_pending_release_waits_for_calm_and_for_no_open_task(pending, gh):
    gh.tip_date = datetime.now(UTC) - timedelta(minutes=1)
    s = WatchSession([pending], pending)
    await merge_watch.watch_pending_release(s)
    assert not events_of(s, "release_pending")
    gh.tip_date = datetime.now(UTC) - timedelta(hours=1)
    merge_watch._last_pending_check.clear()
    s.running_run = 12  # scalar() finds an open task
    await merge_watch.watch_pending_release(s)
    assert not events_of(s, "release_pending")


async def test_pending_release_ignores_a_branch_with_the_bump_or_nothing_new(pending, gh):
    gh.tip_message = "chore(release): 0.7.0"
    s = WatchSession([pending], pending)
    await merge_watch.watch_pending_release(s)
    gh.tip_message, gh.ahead = "feat: c", 0
    merge_watch._last_pending_check.clear()
    await merge_watch.watch_pending_release(s)
    assert not events_of(s, "release_pending")


def test_main_ci_wakeup_text_says_which_version_to_publish():
    from app.orchestrator.prompts import reason_for

    text = reason_for("main_ci", {"branch": "main", "result": "green", "next_step": "Publish v0.7.0 now with publish_version."})
    assert "Publish v0.7.0 now" in text


async def test_main_ci_green_announces_the_version_to_publish(pending, gh, monkeypatch):
    pending.release_ci_sha = pending.main_ci_sha = None
    pending.main_ci_watch = True
    gh.files |= bumped("0.7.0")
    gh.ci = None

    async def branch_head(_repo, _branch):
        return "mainsha"

    monkeypatch.setattr(github, "branch_head", branch_head)
    monkeypatch.setattr(merge_watch, "_last_release_check", {})
    s = WatchSession([pending], pending)
    await merge_watch.watch_release_ci(s)
    [event] = events_of(s, "main_ci")
    assert event.payload["next_step"] == "Publish v0.7.0 now with publish_version."
    assert "publish v0.7.0" in [m for m in s.added if hasattr(m, "content")][0].content


async def test_prepare_release_refuses_a_version_file_it_cannot_bump(gh):
    gh.files["frontend/package.json"] = '{"name": "x", "version": "0.6.1"}'  # Not indented: no match
    with pytest.raises(WorkflowError, match="could not be bumped"):
        await projects.prepare_release(PROJECT)
    assert gh.pushed is None


async def test_publish_version_checks_the_lock_files_too(gh, monkeypatch):
    async def head(_repo, _branch):
        return "mainsha"

    async def no_tag(_repo, _tag):
        return False

    monkeypatch.setattr(github, "branch_head", head)
    monkeypatch.setattr(github, "tag_exists", no_tag)
    gh.ci = None
    gh.files |= bumped("0.7.0")
    gh.files["frontend/package-lock.json"] = LOCK  # Forgotten at 0.6.1
    gh.files["frontend/src-tauri/Cargo.lock"] = CARGO_LOCK
    with pytest.raises(WorkflowError, match="package-lock.json says 0.6.1.*Cargo.lock says 0.6.1"):
        await projects.publish_version(PROJECT, "0.7.0")


async def test_commit_release_pushes_one_commit_to_the_team_branch_only(tmp_path, monkeypatch):
    calls, head = [], {"sha": "tip1"}

    async def git(_cwd, *args, **_kwargs):
        calls.append(args)
        return "new1\n" if args[-2:] == ("rev-parse", "HEAD") and head["sha"] == "new1" else head["sha"] + "\n"

    async def sync(_project):
        (tmp_path / ".git").mkdir(exist_ok=True)
        return tmp_path

    async def resolve(_repo, _branch):
        return "main"

    monkeypatch.setattr(worktrees, "git", git)
    monkeypatch.setattr(worktrees, "_sync_repo", sync)
    monkeypatch.setattr(worktrees, "resolve_branch", resolve)
    monkeypatch.setattr(worktrees, "repo_slug", lambda _url: "acme/app")
    project = SimpleNamespace(id=1, repo_url="https://github.com/acme/app", default_branch="dev")
    head["sha"] = "tip1"  # rev-parse answers the new SHA once the commit is made

    async def git_commit_moves_head(cwd, *args, **kwargs):
        if "commit" in args:
            head["sha"] = "new1"
        return await git(cwd, *args, **kwargs)

    monkeypatch.setattr(worktrees, "git", git_commit_moves_head)
    assert await worktrees.commit_release(project, "tip1", {"v.txt": "2", "sub/w.txt": "x"}, "chore(release): 0.7.0") == "new1"
    assert (tmp_path / "v.txt").read_text() == "2"
    push = [c for c in calls if "push" in c]
    assert push == [("push", "--quiet", "origin", "new1:refs/heads/dev")]  # Never force, never main
    head["sha"] = "other"
    with pytest.raises(github.GitHubError, match="moved"):
        await worktrees.commit_release(project, "tip1", {"v.txt": "3"}, "x")
    with pytest.raises(github.GitHubError, match="Refusing"):
        await worktrees.commit_release(SimpleNamespace(**{**project.__dict__, "default_branch": "main"}), "tip1", {"v.txt": "3"}, "x")
    with pytest.raises(github.GitHubError, match="outside"):
        head["sha"] = "tip1"
        await worktrees.commit_release(project, "tip1", {"../evil": "3"}, "x")


async def test_prepare_release_refuses_a_repository_without_version_files(gh):
    gh.files = {"CHANGELOG.md": CHANGELOG}
    with pytest.raises(WorkflowError, match="No version file"):
        await projects.prepare_release(PROJECT)
    assert gh.pushed is None


async def test_commit_release_refuses_a_symlinked_target(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    (repo / "link.txt").symlink_to(outside / "f.txt")
    (repo / "dirlink").symlink_to(outside)

    async def git(_cwd, *_args, **_kwargs):
        return "tip1\n"

    async def sync(_project):
        return repo

    async def resolve(_repo, _branch):
        return "main"

    monkeypatch.setattr(worktrees, "git", git)
    monkeypatch.setattr(worktrees, "_sync_repo", sync)
    monkeypatch.setattr(worktrees, "resolve_branch", resolve)
    project = SimpleNamespace(id=1, repo_url="https://github.com/acme/app", default_branch="dev")
    for path in ("link.txt", "dirlink/f.txt"):
        with pytest.raises(github.GitHubError, match="Refusing"):
            await worktrees.commit_release(project, "tip1", {path: "x"}, "x")
    assert not (outside / "f.txt").exists()


def test_update_changelog_keeps_every_section_without_a_tag():
    out = release.update_changelog(CHANGELOG, "0.1.0", None, release.changelog_entry("0.1.0", "2026-11-01", ["feat: a"]))
    assert "## [0.6.1]" in out


def test_set_version_bumps_the_compose_image_default():
    text = "image: a:${PALABRE_VERSION:-0.6.1}\nimage: b:${PALABRE_VERSION:-0.6.1}\nx: ${OTHER:-0.6.1}\n"
    out = release.set_version("docker-compose.yml", text, "0.7.0")
    assert out == "image: a:${PALABRE_VERSION:-0.7.0}\nimage: b:${PALABRE_VERSION:-0.7.0}\nx: ${OTHER:-0.6.1}\n"
    assert projects.VERSION_FILES["docker-compose.yml"](out, "") == "0.7.0"
