"""workflow.submit_for_review: a resubmission updates the title of the existing GitHub PR."""

from types import SimpleNamespace

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
        id=7, assignee_id=1, status=TaskStatus.changes_requested, branch="task/7", worktree_path="/tmp/w",
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
    assert calls[0] == ("title", 12, "fix(api): handle x (#7)")


async def test_first_submission_renames_the_branch_before_the_push(monkeypatch):
    gits = []
    task = SimpleNamespace(
        id=7, assignee_id=1, status=TaskStatus.in_progress, branch="task/7", worktree_path="/tmp/w",
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
        return ""

    async def open_pr(repo, **kw):
        opened.update(kw)
        return {"number": 3, "html_url": "u"}

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

    await workflow.submit_for_review(
        FakeSession(), 1, 7, SimpleNamespace(id=1, name="Mehdi"), "sum", False, title="fix(api): handle x"
    )
    assert task.branch == "fix/7-handle-x"
    assert gits[0] == ("/tmp/w", "branch", "-m", "task/7", "fix/7-handle-x")
    assert gits[1][-1] == "fix/7-handle-x"
    assert opened["head"] == "fix/7-handle-x"
