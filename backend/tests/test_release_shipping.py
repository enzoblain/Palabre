"""The lead ships releases alone: merge_release (CI gated) and publish_version (checked tag)."""

import json
from types import SimpleNamespace

import pytest

from app import github, projects, services
from app.models import Decision, DecisionStatus, RequestAnswer
from app.errors import WorkflowError

PROJECT = SimpleNamespace(id=1, repo_url="https://github.com/acme/app", default_branch="dev")
PR = {"number": 42, "html_url": "https://github.com/acme/app/pull/42", "head": {"sha": "pr-head"}}


class FakeSession:
    def __init__(self, pending=None):
        self.pending, self.commits = pending, 0

    async def scalar(self, _query):
        return self.pending

    async def commit(self):
        self.commits += 1


@pytest.fixture
def gh(monkeypatch):
    state = SimpleNamespace(
        calls=[], checked=[], pr=PR, ci=None, prod_ci=None, tags=set(), files={}, release_args=None,
    )

    async def resolve_branch(repo, branch):
        return "main"

    async def find_pull_request(repo, head, base):
        return state.pr

    async def open_pull_request(repo, head, base, title, body):
        state.calls.append(("open", head, base))
        return PR

    async def commit_checks(repo, sha):
        state.checked.append(sha)
        return state.ci if sha == "pr-head" else state.prod_ci

    async def merge(repo, number, title, method="squash", sha=None):
        state.calls.append(("merge", number, method, sha))
        state.merge_title = title

    async def tag_exists(repo, tag):
        return tag in state.tags

    async def branch_head(repo, branch):
        return "abc123"

    async def file_content(repo, path, ref):
        assert ref == "abc123"
        return state.files.get(path)

    async def create_release(repo, tag, sha):
        state.release_args = (tag, sha)
        return {"html_url": f"https://github.com/acme/app/releases/tag/{tag}"}

    for fn in (resolve_branch, find_pull_request, open_pull_request, commit_checks, tag_exists, branch_head,
               file_content, create_release):
        monkeypatch.setattr(github, fn.__name__, fn)
    monkeypatch.setattr(github, "merge_pull_request", merge)
    state.files = versioned("1.2.0")

    async def nothing_to_bump(_project):
        raise projects.NothingToRelease("Nothing worth a release on dev: only chores")

    monkeypatch.setattr(projects, "prepare_release", nothing_to_bump)  # Covered by test_release_auto.py
    return state


def versioned(version: str) -> dict[str, str]:
    return {
        "frontend/package.json": json.dumps({"name": "x", "version": version}),
        "frontend/src-tauri/tauri.conf.json": json.dumps({"version": version}),
        "frontend/src-tauri/Cargo.toml": f'[package]\nname = "x"\nversion = "{version}"\n',
    }


# --- merge_release ---------------------------------------------------------------------


async def test_merge_release_merges_when_ci_is_green(gh):
    url, number = await projects.merge_release(FakeSession(), PROJECT, "Checkout", "Notes")
    assert (url, number) == (PR["html_url"], 42)
    assert gh.calls == [("merge", 42, "merge", "pr-head")]
    assert gh.merge_title == "chore(release): Checkout"


@pytest.mark.parametrize("ci", ["CI failed: backend", "CI still running: tests", "no CI checks reported"])
async def test_merge_release_refuses_without_green_ci(gh, ci):
    gh.ci = ci
    with pytest.raises(WorkflowError, match=ci):
        await projects.merge_release(FakeSession(), PROJECT, "Checkout", "Notes")
    assert gh.calls == []


async def test_merge_release_opens_the_pr_when_missing(gh):
    gh.pr = None
    await projects.merge_release(FakeSession(), PROJECT, "Checkout", "Notes")
    assert gh.calls == [("open", "dev", "main"), ("merge", 42, "merge", "pr-head")]


async def test_merge_release_refuses_when_the_team_works_on_production(gh):
    with pytest.raises(WorkflowError, match="nothing to release"):
        await projects.merge_release(FakeSession(), SimpleNamespace(**{**PROJECT.__dict__, "default_branch": "main"}), "T", "S")


async def test_merge_release_settles_the_release_the_boss_was_asked_about(gh, monkeypatch):
    decision = Decision(id=3, room_id=1, title="Release: Checkout", proposed_by="Louise", pr_number=42,
                        status=DecisionStatus.proposed)  # fmt: skip
    settled = []

    async def settle(s, d, answer, comment="", *, wake_proposer=True, merge_sha=None):
        settled.append((d, answer, wake_proposer, merge_sha))

    monkeypatch.setattr(projects, "settle_decision", settle)
    await projects.merge_release(FakeSession(decision), PROJECT, "Checkout", "Notes")
    assert settled == [(decision, RequestAnswer.validated, False, "pr-head")]
    assert gh.calls == []  # settle_decision does the merge


async def test_merge_release_checks_the_commit_it_pins(gh):
    await projects.merge_release(FakeSession(), PROJECT, "Checkout", "Notes")
    assert gh.checked == ["pr-head"]


async def test_settle_release_merge_commit_is_conventional(gh):
    decision = Decision(id=3, room_id=1, title="Release: Checkout", pr_number=42)
    await projects.settle_release(PROJECT, decision, True, sha="pr-head")
    assert gh.merge_title == "chore(release): Checkout"


# --- publish_version -------------------------------------------------------------------


async def test_publish_version_tags_the_head_of_production(gh):
    url = await projects.publish_version(PROJECT, "1.2.0")
    assert gh.release_args == ("v1.2.0", "abc123")
    assert url.endswith("/v1.2.0")


async def test_publish_version_accepts_a_v_prefix(gh):
    await projects.publish_version(PROJECT, "v1.2.0")
    assert gh.release_args[0] == "v1.2.0"


@pytest.mark.parametrize("version", ["1.2", "1.2.x", "latest", "", "1.2.0-rc1", "1.2.0; rm", "../1.2.0"])
async def test_publish_version_refuses_a_malformed_version(gh, version):
    with pytest.raises(WorkflowError, match="not a version"):
        await projects.publish_version(PROJECT, version)
    assert gh.release_args is None


async def test_publish_version_refuses_an_existing_tag(gh):
    gh.tags.add("v1.2.0")
    with pytest.raises(WorkflowError, match="already exists"):
        await projects.publish_version(PROJECT, "1.2.0")
    assert gh.release_args is None


@pytest.mark.parametrize("path", sorted(versioned("0")))
async def test_publish_version_refuses_files_at_another_version(gh, path):
    gh.files = versioned("1.2.0") | versioned("1.1.9") | {p: v for p, v in versioned("1.2.0").items() if p != path}
    with pytest.raises(WorkflowError, match=path):
        await projects.publish_version(PROJECT, "1.2.0")
    assert gh.release_args is None


async def test_publish_version_refuses_unreadable_version_files(gh):
    gh.files["frontend/package.json"] = "{not json"
    with pytest.raises(WorkflowError, match="unreadable"):
        await projects.publish_version(PROJECT, "1.2.0")


async def test_publish_version_refuses_when_production_is_not_green(gh):
    gh.prod_ci = "CI failed: backend"
    with pytest.raises(WorkflowError, match="not green: CI failed: backend"):
        await projects.publish_version(PROJECT, "1.2.0")
    assert gh.checked == ["abc123"] and gh.release_args is None


# --- release name and notes, fix_release -------------------------------------------------


def test_release_name_and_notes_match_the_hand_made_releases():
    assert github.release_name("v0.2.2") == "Palabre v0.2.2"
    notes = github.release_notes("Enzoblain/Palabre", "v0.2.2")
    assert notes.startswith("Desktop app: download the file for your system below.\n- macOS:")
    assert notes.endswith("\n\nServer: `ghcr.io/enzoblain/palabre:0.2.2` (see the README).")


def test_release_notes_put_the_changes_before_the_download_text():
    notes = github.release_notes("acme/app", "v1.2.0", "### Features\n- a: b")
    assert notes.startswith("### Features\n- a: b\n\nDesktop app:")
    assert notes.endswith(github.release_notes("acme/app", "v1.2.0"))


def test_release_changes_group_commits_by_type():
    changes = github.release_changes([
        "feat(usage): show real usage (#12)\n\nlong body",
        "fix(api): handle 404 (#13)",
        "perf(db): index tasks (#14)",
        "docs: update README (#15)",
        "ci(release): pin actions (#16)",
        "chore: tidy",
        "[#77] Release 0.3.0 : bump",
        "feat: no scope (#17)",
    ])  # fmt: skip
    assert changes == "\n\n".join([
        "### Features\n- usage: show real usage (#12)\n- no scope (#17)",
        "### Bug Fixes\n- api: handle 404 (#13)",
        "### Performance\n- db: index tasks (#14)",
        "### Documentation\n- update README (#15)",
        "### Other\n- release: pin actions (#16)\n- tidy\n- [#77] Release 0.3.0 : bump",
    ])


def test_release_changes_list_breaking_changes_and_skip_empty_sections():
    changes = github.release_changes(["feat(api)!: drop v1 (#1)", "fix: x (#2)\n\nBREAKING CHANGE: y"])
    assert changes.startswith("### Breaking Changes\n- api: drop v1 (#1)\n- x (#2)\n\n### Features")
    assert "Documentation" not in changes and "Other" not in changes
    assert github.release_changes([]) == ""


def test_previous_tag_is_the_highest_lower_version():
    tags = ["v0.10.0", "v0.2.4", "v0.3.0", "latest", "v0.9.1"]
    assert github.previous_tag(tags, "v0.10.0") == "v0.9.1"
    assert github.previous_tag(tags, "v0.3.0") == "v0.2.4"
    assert github.previous_tag(tags, "v0.2.4") is None
    assert github.previous_tag(tags, "v1.0.0") == "v0.10.0"


def fake_github_api(monkeypatch, tags=("v1.1.0", "v1.0.0")):
    sent = []

    async def api(method, path, **kwargs):
        sent.append((method, path, kwargs))
        if path.endswith("/tags"):
            return [{"name": t} for t in tags]
        if "/compare/" in path:
            return {"commits": [
                {"commit": {"message": "fix(a): older (#1)"}, "parents": [1]},
                {"commit": {"message": "Merge pull request"}, "parents": [1, 2]},
                {"commit": {"message": "feat(b): newer (#2)"}, "parents": [1]},
            ]}  # fmt: skip
        return {}

    monkeypatch.setattr(github, "_api", api)
    return sent


async def test_publish_version_uses_the_standard_name_and_notes(monkeypatch):
    sent = fake_github_api(monkeypatch)
    await github.create_release("acme/app", "v1.2.0", "abc123")
    assert ("GET", "/repos/acme/app/compare/v1.1.0...abc123", {}) in sent
    post = sent[-1][2]["json"]
    assert post["name"] == "Palabre v1.2.0"
    changes = "### Features\n- b: newer (#2)\n\n### Bug Fixes\n- a: older (#1)"
    assert post["body"] == github.release_notes("acme/app", "v1.2.0", changes)


async def test_first_release_lists_every_commit(monkeypatch):
    async def api(method, path, **kwargs):
        if path.endswith("/tags"):
            return []
        if path.endswith("/commits"):
            return [{"commit": {"message": "feat: init"}, "parents": []}]
        return {}

    monkeypatch.setattr(github, "_api", api)
    assert await github.release_commits("acme/app", "v0.1.0", "abc") == ["feat: init"]


async def test_fix_release_patches_the_existing_release(gh, monkeypatch):
    gh.tags.add("v1.2.0")
    calls = []

    async def api(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        if path.endswith("/tags"):
            return [{"name": "v1.1.0"}]
        if "/compare/" in path:
            return {"commits": [{"commit": {"message": "feat(b): newer (#2)"}, "parents": [1]}]}
        return {"id": 7, "html_url": "https://github.com/acme/app/releases/tag/v1.2.0"}

    monkeypatch.setattr(github, "_api", api)
    url = await projects.fix_release(PROJECT, "v1.2.0")
    assert url.endswith("/v1.2.0")
    assert calls[0][:2] == ("GET", "/repos/acme/app/releases/tags/v1.2.0")
    assert ("GET", "/repos/acme/app/compare/v1.1.0...v1.2.0", None) in calls
    assert calls[-1] == (
        "PATCH", "/repos/acme/app/releases/7",
        {"name": "Palabre v1.2.0", "body": github.release_notes("acme/app", "v1.2.0", "### Features\n- b: newer (#2)")},
    )  # fmt: skip


async def test_fix_release_refuses_an_unknown_tag_or_version(gh):
    with pytest.raises(WorkflowError, match="does not exist"):
        await projects.fix_release(PROJECT, "1.2.0")
    with pytest.raises(WorkflowError, match="not a version"):
        await projects.fix_release(PROJECT, "latest")


COMPOSE = "services:\n  backend:\n    image: ghcr.io/acme/app:${PALABRE_VERSION:-%s}\n  web:\n    image: ghcr.io/acme/app-web:${PALABRE_VERSION:-%s}\n"


async def test_publish_version_refuses_a_compose_file_pinned_to_another_version(gh):
    gh.files = versioned("1.2.0") | {"docker-compose.yml": COMPOSE % ("1.1.9", "1.1.9")}
    with pytest.raises(WorkflowError, match="docker-compose.yml says 1.1.9"):
        await projects.publish_version(PROJECT, "1.2.0")
    gh.files = versioned("1.2.0") | {"docker-compose.yml": COMPOSE % ("1.2.0", "1.1.9")}
    with pytest.raises(WorkflowError, match="docker-compose.yml"):
        await projects.publish_version(PROJECT, "1.2.0")


async def test_publish_version_accepts_a_matching_or_unversioned_compose_file(gh):
    gh.files = versioned("1.2.0") | {"docker-compose.yml": COMPOSE % ("1.2.0", "1.2.0")}
    await projects.publish_version(PROJECT, "1.2.0")
    gh.files = versioned("1.2.0") | {"docker-compose.yml": "services:\n  a:\n    image: x\n"}
    await projects.publish_version(PROJECT, "1.2.0")
