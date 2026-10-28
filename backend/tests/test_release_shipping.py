"""The lead ships releases alone: merge_release (CI gated) and publish_version (checked tag)."""

import json
from types import SimpleNamespace

import pytest

from app import github, projects, services
from app.models import Decision, DecisionStatus, RequestAnswer
from app.services import WorkflowError

PROJECT = SimpleNamespace(id=1, repo_url="https://github.com/acme/app", default_branch="dev")
PR = {"number": 42, "html_url": "https://github.com/acme/app/pull/42"}


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
        calls=[], pr=PR, ci=None, tags=set(), files={}, release_args=None,
    )

    async def resolve_branch(repo, branch):
        return "main"

    async def find_pull_request(repo, head, base):
        return state.pr

    async def open_pull_request(repo, head, base, title, body):
        state.calls.append(("open", head, base))
        return PR

    async def checks_status(repo, number):
        return state.ci

    async def merge(repo, number, title, method="squash"):
        state.calls.append(("merge", number, method))

    async def tag_exists(repo, tag):
        return tag in state.tags

    async def branch_head(repo, branch):
        return "abc123"

    async def file_content(repo, path, ref):
        assert ref == "abc123"
        return state.files.get(path)

    async def create_release(repo, tag, sha, notes):
        state.release_args = (tag, sha, notes)
        return {"html_url": f"https://github.com/acme/app/releases/tag/{tag}"}

    for fn in (resolve_branch, find_pull_request, open_pull_request, checks_status, tag_exists, branch_head,
               file_content, create_release):
        monkeypatch.setattr(github, fn.__name__, fn)
    monkeypatch.setattr(github, "merge_pull_request", merge)
    state.files = versioned("1.2.0")
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
    assert gh.calls == [("merge", 42, "merge")]


@pytest.mark.parametrize("ci", ["CI failed: backend", "CI still running: tests", "no CI checks reported"])
async def test_merge_release_refuses_without_green_ci(gh, ci):
    gh.ci = ci
    with pytest.raises(WorkflowError, match=ci):
        await projects.merge_release(FakeSession(), PROJECT, "Checkout", "Notes")
    assert gh.calls == []


async def test_merge_release_opens_the_pr_when_missing(gh):
    gh.pr = None
    await projects.merge_release(FakeSession(), PROJECT, "Checkout", "Notes")
    assert gh.calls == [("open", "dev", "main"), ("merge", 42, "merge")]


async def test_merge_release_refuses_when_the_team_works_on_production(gh):
    with pytest.raises(WorkflowError, match="nothing to release"):
        await projects.merge_release(FakeSession(), SimpleNamespace(**{**PROJECT.__dict__, "default_branch": "main"}), "T", "S")


async def test_merge_release_settles_the_release_the_boss_was_asked_about(gh, monkeypatch):
    decision = Decision(id=3, room_id=1, title="Release: Checkout", proposed_by="Louise", pr_number=42,
                        status=DecisionStatus.proposed)  # fmt: skip
    settled = []

    async def settle(s, d, answer, comment="", *, wake_proposer=True):
        settled.append((d, answer, wake_proposer))

    monkeypatch.setattr(projects, "settle_decision", settle)
    await projects.merge_release(FakeSession(decision), PROJECT, "Checkout", "Notes")
    assert settled == [(decision, RequestAnswer.validated, False)]
    assert gh.calls == []  # settle_decision does the merge


# --- publish_version -------------------------------------------------------------------


async def test_publish_version_tags_the_head_of_production(gh):
    url = await projects.publish_version(PROJECT, "1.2.0", " Fixes ")
    assert gh.release_args == ("v1.2.0", "abc123", "Fixes")
    assert url.endswith("/v1.2.0")


async def test_publish_version_accepts_a_v_prefix(gh):
    await projects.publish_version(PROJECT, "v1.2.0", "Notes")
    assert gh.release_args[0] == "v1.2.0"


@pytest.mark.parametrize("version", ["1.2", "1.2.x", "latest", "", "1.2.0-rc1", "1.2.0; rm", "../1.2.0"])
async def test_publish_version_refuses_a_malformed_version(gh, version):
    with pytest.raises(WorkflowError, match="not a version"):
        await projects.publish_version(PROJECT, version, "Notes")
    assert gh.release_args is None


async def test_publish_version_refuses_an_existing_tag(gh):
    gh.tags.add("v1.2.0")
    with pytest.raises(WorkflowError, match="already exists"):
        await projects.publish_version(PROJECT, "1.2.0", "Notes")
    assert gh.release_args is None


@pytest.mark.parametrize("path", sorted(versioned("0")))
async def test_publish_version_refuses_files_at_another_version(gh, path):
    gh.files = versioned("1.2.0") | versioned("1.1.9") | {p: v for p, v in versioned("1.2.0").items() if p != path}
    with pytest.raises(WorkflowError, match=path):
        await projects.publish_version(PROJECT, "1.2.0", "Notes")
    assert gh.release_args is None


async def test_publish_version_refuses_unreadable_version_files(gh):
    gh.files["frontend/package.json"] = "{not json"
    with pytest.raises(WorkflowError, match="unreadable"):
        await projects.publish_version(PROJECT, "1.2.0", "Notes")


async def test_publish_version_needs_notes(gh):
    with pytest.raises(WorkflowError, match="notes"):
        await projects.publish_version(PROJECT, "1.2.0", "  ")
