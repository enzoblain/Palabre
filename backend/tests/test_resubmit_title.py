"""workflow.submit_for_review: a resubmission updates the title of the existing GitHub PR."""

from types import SimpleNamespace

import pytest

from app import github, workflow, worktrees
from app.models import TaskStatus


class FakeSession:
    async def get(self, model, pk):
        return SimpleNamespace(repo_url="https://github.com/acme/app", default_branch="dev", mode=None)

    async def commit(self):
        pass


async def test_resubmission_patches_the_pr_title(monkeypatch):
    calls = []
    task = SimpleNamespace(
        id=7, project_id=1, assignee_id=1, status=TaskStatus.changes_requested, branch="task/7", worktree_path="/tmp/w",
        pr_number=12, pr_url="u", pr_title="old", acceptance_criteria=[], description="", review_round=1,
        sensitive=False, conversation_id=1, title="T", merge_ready_at=None, lead_reminded_at=None,
    )

    async def get_task(*_):
        return task

    async def commits_ahead(*_):
        return 1

    async def git(*_, **__):
        return ""

    async def set_title(repo, number, title):
        calls.append(("title", number, title))

    async def comment(repo, number, body):
        calls.append(("comment", number))

    async def noop(*_, **__):
        pass

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "_commits_ahead", commits_ahead)
    monkeypatch.setattr(workflow, "announce", noop)
    monkeypatch.setattr(workflow, "post_message", noop)
    monkeypatch.setattr(workflow, "emit_event", lambda *_, **__: None)
    monkeypatch.setattr(workflow, "mode_process", lambda _: {"qa_gate": False, "security_gate": False})
    monkeypatch.setattr(github, "git", git)
    monkeypatch.setattr(github, "set_pull_request_title", set_title)
    monkeypatch.setattr(github, "comment_pull_request", comment)

    await workflow.submit_for_review(
        FakeSession(), 1, 7, SimpleNamespace(id=1, name="Mehdi"), "sum", False, title="fix(api): handle x"
    )
    assert calls[0] == ("title", 12, "fix(api): handle x (#12)")


async def test_first_submission_renames_the_branch_before_the_push(monkeypatch):
    gits = []
    task = SimpleNamespace(
        id=7, project_id=1, assignee_id=1, status=TaskStatus.in_progress, branch="task/7", worktree_path="/tmp/w",
        pr_number=None, pr_url=None, pr_title=None, acceptance_criteria=[], description="", review_round=0,
        sensitive=False, conversation_id=1, title="T", merge_ready_at=None, lead_reminded_at=None,
    )
    opened = {}

    async def get_task(*_):
        return task

    async def commits_ahead(*_):
        return 1

    async def git(*args, **__):
        gits.append(args)
        return "task/7\n" if "--abbrev-ref" in args else ""

    async def open_pr(repo, **kw):
        opened.update(kw)
        return {"number": 3, "html_url": "u"}

    titles = []

    async def set_title(repo, number, title):
        titles.append((number, title))

    async def noop(*_, **__):
        pass

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "_commits_ahead", commits_ahead)
    monkeypatch.setattr(workflow, "announce", noop)
    monkeypatch.setattr(workflow, "post_message", noop)
    monkeypatch.setattr(workflow, "emit_event", lambda *_, **__: None)
    monkeypatch.setattr(workflow, "mode_process", lambda _: {"qa_gate": False, "security_gate": False})
    monkeypatch.setattr(github, "git", git)
    monkeypatch.setattr(worktrees, "git", git)
    monkeypatch.setattr(github, "open_pull_request", open_pr)
    monkeypatch.setattr(github, "set_pull_request_title", set_title)

    await workflow.submit_for_review(
        FakeSession(), 1, 7, SimpleNamespace(id=1, name="Mehdi"), "sum", False, title="fix(api): handle x"
    )
    assert task.branch == "fix/7-handle-x"
    assert ("/tmp/w", "branch", "-m", "task/7", "fix/7-handle-x") in gits
    assert gits[-1][-1] == "fix/7-handle-x"
    assert opened["head"] == "fix/7-handle-x"
    assert opened["title"] == "fix(api): handle x"
    assert task.pr_title == "fix(api): handle x (#3)"
    assert "Palabre task #7" in opened["body"]
    assert titles == [(3, "fix(api): handle x (#3)")]


async def test_failed_push_after_rename_can_be_resubmitted(monkeypatch):
    task = SimpleNamespace(
        id=7, project_id=1, assignee_id=1, status=TaskStatus.in_progress, branch="task/7", worktree_path="/tmp/w",
        pr_number=None, pr_url=None, pr_title=None, acceptance_criteria=[], description="", review_round=0,
        sensitive=False, conversation_id=1, title="T", merge_ready_at=None, lead_reminded_at=None,
    )
    head = {"branch": "task/7"}  # the worktree's real branch
    fail = {"push": True}

    async def noop(*_, **__):
        pass

    async def get_task(*_):
        return task

    async def commits_ahead(*_):
        return 1

    async def git(path, *args, **__):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return head["branch"] + "\n"
        if args[0] == "branch":
            assert args[2] == head["branch"], "renaming a branch that no longer exists"
            head["branch"] = args[3]
        if args[0] == "push" or "--set-upstream" in args:
            if fail["push"]:
                fail["push"] = False
                raise github.GitHubError("network")
        return ""

    async def open_pr(repo, **kw):
        return {"number": 3, "html_url": "u"}

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "_commits_ahead", commits_ahead)
    monkeypatch.setattr(workflow, "announce", noop)
    monkeypatch.setattr(workflow, "post_message", noop)
    monkeypatch.setattr(workflow, "emit_event", lambda *_, **__: None)
    monkeypatch.setattr(workflow, "mode_process", lambda _: {"qa_gate": False, "security_gate": False})
    monkeypatch.setattr(github, "git", git)
    monkeypatch.setattr(worktrees, "git", git)
    monkeypatch.setattr(github, "open_pull_request", open_pr)
    monkeypatch.setattr(github, "set_pull_request_title", noop)

    author = SimpleNamespace(id=1, name="Mehdi")
    with pytest.raises(github.GitHubError):
        await workflow.submit_for_review(FakeSession(), 1, 7, author, "sum", False, title="fix(api): handle x")
    task.branch = "task/7"  # the rollback restored the old value
    await workflow.submit_for_review(FakeSession(), 1, 7, author, "sum", False, title="feat(api): handle y")
    assert task.branch == "feat/7-handle-y"
    assert head["branch"] == "feat/7-handle-y"
