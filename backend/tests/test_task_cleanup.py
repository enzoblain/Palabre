"""workflow.clean_up_task and clean_up_finished_tasks: what is deleted, and what never is."""

from types import SimpleNamespace

import httpx
import pytest

from app import github, workflow
from app.models import TaskStatus

from .conftest import make_project, make_task


@pytest.fixture
def gh(monkeypatch):
    """Records GitHub and worktree calls; `open_prs` holds the numbers of open PRs."""
    state = SimpleNamespace(calls=[], open_prs={42}, fail_delete=None, fail_git=False)

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

    async def git(_cwd, *args, **_):
        state.calls.append(("git", *args))
        if state.fail_git:
            raise github.GitHubError("git update-ref failed")
        return ""

    monkeypatch.setattr(github, "git", git)
    monkeypatch.setattr(workflow, "repo_dir", lambda _project: "/ref")
    monkeypatch.setattr(github, "is_pull_request_open", is_open)
    monkeypatch.setattr(github, "close_pull_request", close)
    monkeypatch.setattr(github, "delete_branch", delete)
    monkeypatch.setattr(workflow, "remove_task_worktree", remove_worktree)
    return state


async def test_cancelled_task_loses_its_open_pr_and_branch(gh):
    task = make_task(status=TaskStatus.cancelled, worktree_path="/w")
    await workflow.clean_up_task(make_project(), task)
    assert gh.calls == [("git", "update-ref", "-d", f"refs/palabre/reviewed/{task.id}"), ("close", 42), ("delete", "task/1-demo"), ("worktree", task.id)]
    assert task.worktree_path is None


async def test_reviewed_ref_is_dropped_and_its_failure_does_not_block(gh):
    gh.fail_git = True
    task = make_task(status=TaskStatus.done, worktree_path="/w")
    await workflow.clean_up_task(make_project(), task)
    assert ("git", "update-ref", "-d", f"refs/palabre/reviewed/{task.id}") in gh.calls
    assert ("delete", "task/1-demo") in gh.calls and task.worktree_path is None


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
    gh.fail_delete = github.GitHubError("GitHub DELETE: 500", status=500)
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
        raise github.GitHubError("GitHub GET /repos/a/b/pulls/9: 404 Not Found", status=404)

    monkeypatch.setattr(github, "_api", api)
    assert await github.is_pull_request_open("a/b", 9) is False


async def test_non_404_error_on_pull_request_is_raised(monkeypatch):
    async def api(*_args, **_kwargs):
        raise github.GitHubError("GitHub GET /repos/a/b/pulls/9: 500 boom", status=500)

    monkeypatch.setattr(github, "_api", api)
    with pytest.raises(github.GitHubError) as caught:
        await github.is_pull_request_open("a/b", 9)
    assert caught.value.status == 500


@pytest.mark.parametrize("status", [404, 500])
async def test_api_error_carries_the_http_status(monkeypatch, status):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _request: httpx.Response(status, text="nope"))
    monkeypatch.setattr(github.settings, "github_token", "t")
    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    with pytest.raises(github.GitHubError) as caught:
        await github._api("GET", "/repos/a/b")
    assert caught.value.status == status
    assert github.GitHubError("git failed").status is None
