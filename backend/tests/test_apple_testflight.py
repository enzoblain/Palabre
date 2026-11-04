"""TestFlight publication of a Swift project: gates, version and the workflow template."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app import apple, github
from app.errors import WorkflowError
from app.models import ProjectPlatform

TEMPLATE = Path(__file__).parents[2] / "deploy" / "apple-templates" / "swift-testflight.yml"
PROJECT = SimpleNamespace(repo_url="https://github.com/acme/app", platform=ProjectPlatform.apple)


@pytest.fixture
def github_calls(monkeypatch):
    """Fakes GitHub: the latest tag, the verdict of its checks and the dispatch; records the dispatches."""
    state = SimpleNamespace(tag="v1.2.3", checks=None, dispatch_error=None, dispatched=[])

    async def latest_version_tag(_repo):
        return state.tag

    async def tag_commit(_repo, _tag):
        return "abc123"

    async def commit_checks(_repo, _sha):
        return state.checks

    async def dispatch_workflow(repo, workflow_file, ref, inputs):
        if state.dispatch_error:
            raise state.dispatch_error
        state.dispatched.append((repo, workflow_file, ref, inputs))

    monkeypatch.setattr(github, "latest_version_tag", latest_version_tag)
    monkeypatch.setattr(github, "tag_commit", tag_commit)
    monkeypatch.setattr(github, "commit_checks", commit_checks)
    monkeypatch.setattr(github, "dispatch_workflow", dispatch_workflow)
    return state


async def test_publishes_the_version_of_the_latest_release(github_calls):
    assert await apple.publish_testflight(PROJECT) == "1.2.3"
    assert github_calls.dispatched == [("acme/app", "swift-testflight.yml", "v1.2.3", {"version": "1.2.3"})]


async def test_refuses_a_project_that_is_not_swift(github_calls):
    generic = SimpleNamespace(repo_url=PROJECT.repo_url, platform=ProjectPlatform.generic)
    with pytest.raises(WorkflowError) as refused:
        await apple.publish_testflight(generic)
    assert refused.value.code == "apple_publish_not_apple"
    assert not github_calls.dispatched


async def test_refuses_without_a_release(github_calls):
    github_calls.tag = None
    with pytest.raises(WorkflowError) as refused:
        await apple.publish_testflight(PROJECT)
    assert refused.value.code == "apple_publish_no_release"


@pytest.mark.parametrize("reason", ["CI failed: Build", "CI still running: Build"])
async def test_refuses_when_the_build_is_not_green(github_calls, reason):
    github_calls.checks = reason
    with pytest.raises(WorkflowError) as refused:
        await apple.publish_testflight(PROJECT)
    assert refused.value.code == "apple_publish_build_not_green"
    assert not github_calls.dispatched


async def test_tag_without_checks_relies_on_the_workflow_test_job(github_calls):
    github_calls.checks = github.NO_CHECKS_REASON
    assert await apple.publish_testflight(PROJECT) == "1.2.3"


@pytest.mark.parametrize("status", [404, 422])
async def test_missing_workflow_is_a_readable_error(github_calls, status):
    github_calls.dispatch_error = github.GitHubError("no workflow", status=status)
    with pytest.raises(WorkflowError) as refused:
        await apple.publish_testflight(PROJECT)
    assert refused.value.code == "apple_publish_workflow_missing"


async def test_other_github_errors_are_not_hidden(github_calls):
    github_calls.dispatch_error = github.GitHubError("boom", status=500)
    with pytest.raises(github.GitHubError):
        await apple.publish_testflight(PROJECT)


def _workflow() -> dict:
    return yaml.safe_load(TEMPLATE.read_text())


def test_template_reads_the_apple_secrets_only_in_the_protected_signing_job():
    jobs = _workflow()["jobs"]
    for name, job in jobs.items():
        holds_secrets = "secrets." in yaml.safe_dump(job)
        assert holds_secrets == (name == "testflight")
    assert jobs["testflight"]["environment"] == "testflight"
    assert jobs["testflight"]["needs"] == "archive"
    assert jobs["archive"]["needs"] == "test"
    assert jobs["test"]["needs"] == "verify"


def test_template_runs_no_repository_code_in_the_job_that_holds_the_keys():
    steps = _workflow()["jobs"]["testflight"]["steps"]
    assert not any(step.get("uses", "").startswith("actions/checkout") for step in steps)
    script = "\n".join(step.get("run", "") for step in steps)
    assert "xcodebuild archive" not in script and "xcodebuild test" not in script
    assert " -A " not in script  # the key is usable by codesign only
    assert "-T /usr/bin/codesign" in script
    assert not any(step.get("uses", "").startswith("./") for step in steps)  # no local action from the repository
    assert any(step.get("uses", "").startswith("actions/download-artifact") for step in steps)


def test_template_archives_unsigned_in_a_job_without_secrets():
    job = _workflow()["jobs"]["archive"]
    assert "environment" not in job
    script = "\n".join(step.get("run", "") for step in job["steps"])
    assert "xcodebuild archive" in script and "CODE_SIGNING_ALLOWED=NO" in script
    assert any(step.get("uses", "").startswith("actions/upload-artifact") for step in job["steps"])


def test_template_is_manual_only_with_read_permissions_and_pinned_actions():
    workflow = _workflow()
    assert set(workflow[True]) == {"workflow_dispatch"}  # YAML reads the key `on` as True
    assert workflow["permissions"] == {"contents": "read"}
    for line in TEMPLATE.read_text().splitlines():
        if "uses:" in line:
            assert "@" in line and len(line.split("@")[1].split()[0]) == 40
