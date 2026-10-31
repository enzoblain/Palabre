"""The lead closes PRs no task owns (Dependabot, humans) and deletes their branch, nothing else."""

from types import SimpleNamespace

import pytest

from app import github, projects
from app.errors import WorkflowError

PROJECT = SimpleNamespace(id=1, repo_url="https://github.com/acme/app", default_branch="dev")


class FakeSession:
    def __init__(self, task_id=None):
        self.task_id = task_id

    async def scalar(self, _query):
        return self.task_id


def pull(head: str, repo: str = "acme/app", state: str = "open") -> dict:
    return {
        "number": 7, "state": state, "html_url": "https://github.com/acme/app/pull/7",
        "head": {"ref": head, "repo": {"full_name": repo}},
    }  # fmt: skip


@pytest.fixture
def gh(monkeypatch):
    state = SimpleNamespace(pr=pull("dependabot/github_actions/dev/actions/checkout-7.0.1"), calls=[])

    async def resolve_branch(repo, branch):
        return "main"

    async def get_pull_request(repo, number):
        return state.pr

    async def comment_pull_request(repo, number, body):
        state.calls.append(("comment", number, body))

    async def close_pull_request(repo, number):
        state.calls.append(("close", number))

    async def delete_branch(repo, branch):
        state.calls.append(("delete", branch))

    for fn in (resolve_branch, get_pull_request, comment_pull_request, close_pull_request, delete_branch):
        monkeypatch.setattr(github, fn.__name__, fn)
    return state


async def test_closes_a_dependabot_pr_and_deletes_its_branch(gh):
    result = await projects.close_outside_pull_request(FakeSession(), PROJECT, 7, "We stay on v4")
    branch = "dependabot/github_actions/dev/actions/checkout-7.0.1"
    assert gh.calls == [("comment", 7, "We stay on v4"), ("close", 7), ("delete", branch)]
    assert result["branch_deleted"] == branch


async def test_refuses_a_task_pr(gh):
    with pytest.raises(WorkflowError, match="task #3"):
        await projects.close_outside_pull_request(FakeSession(task_id=3), PROJECT, 7, "No")
    assert gh.calls == []


async def test_refuses_the_release_pr(gh):
    gh.pr = pull("dev")
    with pytest.raises(WorkflowError, match="release PR"):
        await projects.close_outside_pull_request(FakeSession(), PROJECT, 7, "No")
    assert gh.calls == []


async def test_refuses_a_closed_pr(gh):
    gh.pr = pull("dependabot/x", state="closed")
    with pytest.raises(WorkflowError, match="already closed"):
        await projects.close_outside_pull_request(FakeSession(), PROJECT, 7, "No")


@pytest.mark.parametrize("head, repo", [("feature", "someone/app"), ("main", "acme/app"), ("task/12-x", "acme/app")])
async def test_keeps_forks_and_protected_branches(gh, head, repo):
    gh.pr = pull(head, repo)
    result = await projects.close_outside_pull_request(FakeSession(), PROJECT, 7, "No")
    assert ("close", 7) in gh.calls and not any(call[0] == "delete" for call in gh.calls)
    assert result["branch_deleted"] is None
