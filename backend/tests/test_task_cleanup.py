"""workflow.clean_up_task and clean_up_finished_tasks: what is deleted, and what never is."""

from types import SimpleNamespace

import pytest

from app import github, workflow
from app.models import TaskStatus

from .conftest import make_project, make_task


@pytest.fixture
def gh(monkeypatch):
    """Records GitHub and worktree calls; `open_prs` holds the numbers of open PRs."""
    state = SimpleNamespace(calls=[], open_prs={42}, fail_delete=None)

    async def is_open(_repo, number):
        return number in state.open_prs

    async def close(_repo, number):
        state.calls.append(("close", number))

    async def delete(_repo, branch):
        if state.fail_delete:
            raise state.fail_delete
        state.calls.append(("delete", branch))

    async def remove_worktree(_project, task):
        state.calls.append(("worktree", task.id))

    monkeypatch.setattr(github, "is_pull_request_open", is_open)
    monkeypatch.setattr(github, "close_pull_request", close)
    monkeypatch.setattr(github, "delete_branch", delete)
    monkeypatch.setattr(workflow, "remove_task_worktree", remove_worktree)
    return state


async def test_cancelled_task_loses_its_open_pr_and_branch(gh):
    task = make_task(status=TaskStatus.cancelled, worktree_path="/w")
    await workflow.clean_up_task(make_project(), task)
    assert gh.calls == [("close", 42), ("delete", "task/1-demo"), ("worktree", task.id)]
    assert task.worktree_path is None


async def test_merged_task_pr_is_not_closed_again(gh):
    gh.open_prs = set()
    task = make_task(status=TaskStatus.done)
    await workflow.clean_up_task(make_project(), task)
    assert ("close", 42) not in gh.calls
    assert ("delete", "task/1-demo") in gh.calls


@pytest.mark.parametrize("branch", ["main", "dev", "release/1.0", None])
async def test_only_task_branches_are_deleted(gh, branch):
    await workflow.clean_up_task(make_project(), make_task(status=TaskStatus.done, branch=branch))
    assert not [c for c in gh.calls if c[0] == "delete"]


async def test_github_error_is_logged_not_raised(gh):
    gh.fail_delete = github.GitHubError("GitHub DELETE: 500")
    task = make_task(status=TaskStatus.cancelled, worktree_path="/w")
    await workflow.clean_up_task(make_project(), task)  # must not raise
    assert task.worktree_path == "/w"


async def test_cleanup_twice_is_harmless(gh):
    task = make_task(status=TaskStatus.cancelled)
    await workflow.clean_up_task(make_project(), task)
    gh.open_prs = set()
    await workflow.clean_up_task(make_project(), task)
    assert gh.calls.count(("close", 42)) == 1


async def test_backlog_visits_finished_tasks_only_with_known_branches(gh):
    project = make_project()
    project.id = 7
    done = make_task(project_id=7, status=TaskStatus.done)
    nothing = make_task(project_id=7, status=TaskStatus.cancelled, branch=None, pr_number=None)

    class Session:
        committed = False

        async def scalars(self, _q):
            return SimpleNamespace(all=lambda: [done, nothing])

        async def get(self, _model, _id):
            return project

        async def commit(self):
            self.committed = True

    s = Session()
    assert await workflow.clean_up_finished_tasks(s) == 2
    assert ("delete", "task/1-demo") in gh.calls
    assert [c for c in gh.calls if c[0] == "delete"] == [("delete", "task/1-demo")]
    assert s.committed


async def test_missing_pull_request_counts_as_not_open(monkeypatch):
    async def api(*_args, **_kwargs):
        raise github.GitHubError("GitHub GET /repos/a/b/pulls/9: 404 Not Found")

    monkeypatch.setattr(github, "_api", api)
    assert await github.is_pull_request_open("a/b", 9) is False
