"""The merge is pinned to the PR head the merge rules were checked on."""

import pytest

from app import github, workflow
from app.errors import ErrorCode, WorkflowError
from tests.conftest import make_employee, make_task
from tests.test_context_reset import WorkflowDb

HEAD = "a" * 40


@pytest.fixture
def merge(monkeypatch):
    """merge_task with GitHub mocked: `state.merged_with` records the sha, `state.refuse` makes GitHub answer 409."""
    from types import SimpleNamespace

    state = SimpleNamespace(merged_with=None, ci_sha=None, refuse=False)
    task = make_task(
        project_id=1, depends_on=[], title="T", conversation_id=1, pr_url=None, pr_title="feat: x",
        pr_number=7, status=workflow.TaskStatus.review, closed_by_id=None, closed_at=None,
    )

    async def nothing(*_, **__):
        pass

    async def get_task(*_):
        return task

    async def pull_request_head(*_):
        return HEAD

    async def checks_status(_repo, _number, sha=None):
        state.ci_sha = sha

    async def merge_pull_request(_repo, _number, _title, method="squash", sha=None):
        state.merged_with = sha
        if state.refuse:
            raise github.GitHubError("GitHub PUT: 409 head branch was modified", status=github.HTTP_CONFLICT)

    for name in ("clean_up_task", "announce"):
        monkeypatch.setattr(workflow, name, nothing)
    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "post_message", nothing)
    monkeypatch.setattr(workflow, "mode_process", lambda _mode: {
        "required_approvals": 0, "qa_gate": False, "security_gate": False, "ci_required": True, "docs_required": False,
    })
    monkeypatch.setattr(workflow, "_task_reviews", lambda *_: _empty())
    monkeypatch.setattr(github, "pull_request_head", pull_request_head)
    monkeypatch.setattr(github, "checks_status", checks_status)
    monkeypatch.setattr(github, "merge_pull_request", merge_pull_request)
    state.task = task
    return state


async def _empty():
    return []


async def test_the_merge_is_pinned_to_the_head_the_ci_was_checked_on(merge):
    await workflow.merge_task(WorkflowDb(0), 1, merge.task.id, make_employee("Élise", "lead"))
    assert merge.merged_with == HEAD and merge.ci_sha == HEAD


async def test_a_rebased_head_that_is_not_the_reviewed_one_stays_mergeable(merge):
    merge.task.reviewed_head = "b" * 40  # pure rebase: the approvals were given on the pre-rebase commit
    await workflow.merge_task(WorkflowDb(0), 1, merge.task.id, make_employee("Élise", "lead"))
    assert merge.merged_with == HEAD


async def test_a_head_that_moved_after_the_gates_fails_the_merge_with_a_clear_reason(merge):
    merge.refuse = True
    with pytest.raises(WorkflowError, match="head moved") as exc:
        await workflow.merge_task(WorkflowDb(0), 1, merge.task.id, make_employee("Élise", "lead"))
    assert exc.value.code == ErrorCode.MERGE_BLOCKED
    assert merge.task.status == workflow.TaskStatus.review


async def test_another_github_error_is_not_mistaken_for_a_moved_head(merge, monkeypatch):
    async def refuse(*_a, **_k):
        raise github.GitHubError("boom", status=500)

    monkeypatch.setattr(github, "merge_pull_request", refuse)
    with pytest.raises(github.GitHubError):
        await workflow.merge_task(WorkflowDb(0), 1, merge.task.id, make_employee("Élise", "lead"))
