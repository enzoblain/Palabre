"""merge_task pins the merge on the PR head it checked: a moved head is refused with a clear error."""

import pytest

from app import github, workflow
from app.errors import ErrorCode, WorkflowError

from .conftest import make_project, make_task
from .test_context_reset import WorkflowDb, lead_flow

HEAD = "a" * 40


@pytest.fixture
def merge(monkeypatch):
    """A merge_task setup whose PR head is HEAD; `calls` records the sha given to GitHub."""
    task, lead = lead_flow(monkeypatch)
    calls = []

    async def get_pull_request(*_):
        return {"head": {"sha": HEAD}}

    async def merge_pull_request(*_args, sha=None):
        calls.append(sha)

    monkeypatch.setattr(github, "get_pull_request", get_pull_request)
    monkeypatch.setattr(github, "merge_pull_request", merge_pull_request)
    monkeypatch.setattr(workflow, "post_message", lambda *_: _noop())
    task.status, task.pr_number, task.reviewed_head = workflow.TaskStatus.review, 42, HEAD
    return task, lead, calls


async def _noop():
    return None


async def test_the_merge_is_pinned_on_the_reviewed_head(merge):
    task, lead, calls = merge
    await workflow.merge_task(WorkflowDb(0), 1, task.id, lead)
    assert calls == [HEAD]


async def test_a_pure_rebase_is_merged_on_its_new_head(merge, monkeypatch):
    task, lead, calls = merge
    task.reviewed_head = "b" * 40

    async def pure_rebase(*_):
        return True

    monkeypatch.setattr(workflow, "_is_pure_rebase", pure_rebase)
    await workflow.merge_task(WorkflowDb(0), 1, task.id, lead)
    assert calls == [HEAD]


async def test_a_head_changed_since_the_review_is_refused(merge, monkeypatch):
    task, lead, calls = merge
    task.reviewed_head = "b" * 40

    async def not_a_rebase(*_):
        return False

    monkeypatch.setattr(workflow, "_is_pure_rebase", not_a_rebase)
    with pytest.raises(WorkflowError) as error:
        await workflow.merge_task(WorkflowDb(0), 1, task.id, lead)
    assert error.value.code == ErrorCode.PR_HEAD_MOVED and not calls


async def test_a_head_moved_during_the_merge_gives_a_clear_error(merge, monkeypatch):
    task, lead, _ = merge

    async def refuse(*_args, sha=None):
        raise github.GitHubError("409 Head branch was modified", status=github.HTTP_CONFLICT)

    monkeypatch.setattr(github, "merge_pull_request", refuse)
    with pytest.raises(WorkflowError) as error:
        await workflow.merge_task(WorkflowDb(0), 1, task.id, lead)
    assert error.value.code == ErrorCode.PR_HEAD_MOVED and "moved" in str(error.value)


async def test_another_github_error_is_not_masked(merge, monkeypatch):
    task, lead, _ = merge

    async def broken(*_args, sha=None):
        raise github.GitHubError("500", status=500)

    monkeypatch.setattr(github, "merge_pull_request", broken)
    with pytest.raises(github.GitHubError):
        await workflow.merge_task(WorkflowDb(0), 1, task.id, lead)


async def test_the_blockers_are_checked_on_the_pinned_head(merge, monkeypatch):
    task, lead, calls = merge
    checked = []

    async def blockers(_s, _project, _task, ci_head=None):
        checked.append(ci_head)
        return []

    monkeypatch.setattr(workflow, "merge_blockers", blockers)
    await workflow.merge_task(WorkflowDb(0), 1, task.id, lead)
    assert checked == [HEAD] and calls == [HEAD]


async def test_the_ci_status_is_read_on_the_given_commit(monkeypatch):
    asked = []

    async def commit_checks(_repo, sha):
        asked.append(sha)

    monkeypatch.setattr(github, "commit_checks", commit_checks)
    assert await github.checks_status("o/r", 42, sha=HEAD) is None
    assert asked == [HEAD]


async def test_a_missing_reviewed_head_is_refused(merge):
    task, lead, calls = merge
    task.reviewed_head = None
    with pytest.raises(WorkflowError) as error:
        await workflow.merge_task(WorkflowDb(0), 1, task.id, lead)
    assert error.value.code == ErrorCode.PR_HEAD_MOVED and "reviewed" in str(error.value) and not calls


async def test_a_missing_reviewed_head_is_allowed_with_force(merge):
    task, lead, calls = merge
    task.reviewed_head = None
    await workflow.merge_task(WorkflowDb(0), 1, task.id, lead, force=True)
    assert calls == [HEAD]
