"""workflow.submit_for_review: a resubmission updates the title of the existing GitHub PR."""

from types import SimpleNamespace

import pytest

from app import github, workflow, worktrees
from app.models import TaskStatus


async def no_pr(*_):
    return None


class FakeSession:
    async def get(self, model, pk):
        return SimpleNamespace(id=1, repo_url="https://github.com/acme/app", default_branch="dev", mode=None)

    async def commit(self):
        pass


async def test_resubmission_patches_the_pr_title(monkeypatch):
    calls = []
    task = SimpleNamespace(
        id=7, project_id=1, assignee_id=1, status=TaskStatus.changes_requested, branch="task/7", worktree_path="/tmp/w",
        pr_number=12, pr_url="u", pr_title="old", acceptance_criteria=[], description="", review_round=1,
        sensitive=False, conversation_id=1, title="T", merge_ready_at=None, lead_reminded_at=None, reviewed_head=None,
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
    monkeypatch.setattr(workflow, "push_task_branch", noop)
    monkeypatch.setattr(github, "find_pull_request", no_pr)
    monkeypatch.setattr(github, "set_pull_request_title", set_title)
    monkeypatch.setattr(github, "comment_pull_request", comment)

    await workflow.submit_for_review(
        FakeSession(), 1, 7, SimpleNamespace(id=1, name="Mehdi"), "sum", False, title="fix(api): handle x"
    )
    assert calls[0] == ("title", 12, "fix(api): handle x")


async def test_first_submission_renames_the_branch_before_the_push(monkeypatch):
    gits = []
    task = SimpleNamespace(
        id=7, project_id=1, assignee_id=1, status=TaskStatus.in_progress, branch="task/7", worktree_path="/tmp/w",
        pr_number=None, pr_url=None, pr_title=None, acceptance_criteria=["Un critère en français"],
        description="Une description en français", review_round=0,
        sensitive=False, conversation_id=1, title="T", merge_ready_at=None, lead_reminded_at=None, reviewed_head=None,
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
    async def push(project, task):
        gits.append(("push", task.branch))

    monkeypatch.setattr(github, "git", git)
    monkeypatch.setattr(worktrees, "git", git)
    monkeypatch.setattr(workflow, "push_task_branch", push)
    monkeypatch.setattr(github, "open_pull_request", open_pr)
    monkeypatch.setattr(github, "find_pull_request", no_pr)
    monkeypatch.setattr(github, "set_pull_request_title", set_title)

    await workflow.submit_for_review(
        FakeSession(), 1, 7, SimpleNamespace(id=1, name="Mehdi"), "sum", False, title="fix(api): handle x"
    )
    assert task.branch == "fix/7-handle-x"
    assert ("/tmp/w", "branch", "-m", "task/7", "fix/7-handle-x") in gits
    assert ("push", "fix/7-handle-x") in gits
    assert opened["head"] == "fix/7-handle-x"
    assert opened["title"] == "fix(api): handle x"
    assert "français" not in opened["body"]
    assert opened["body"].startswith("sum")
    assert task.pr_title == "fix(api): handle x"
    assert "Palabre task #7" in opened["body"]
    assert titles == []


async def test_failed_push_after_rename_can_be_resubmitted(monkeypatch):
    task = SimpleNamespace(
        id=7, project_id=1, assignee_id=1, status=TaskStatus.in_progress, branch="task/7", worktree_path="/tmp/w",
        pr_number=None, pr_url=None, pr_title=None, acceptance_criteria=[], description="", review_round=0,
        sensitive=False, conversation_id=1, title="T", merge_ready_at=None, lead_reminded_at=None, reviewed_head=None,
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
        return ""

    async def push(project, task):
        if fail["push"]:
            fail["push"] = False
            raise github.GitHubError("network")

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
    monkeypatch.setattr(workflow, "push_task_branch", push)
    monkeypatch.setattr(github, "open_pull_request", open_pr)
    monkeypatch.setattr(github, "find_pull_request", no_pr)
    monkeypatch.setattr(github, "set_pull_request_title", noop)

    author = SimpleNamespace(id=1, name="Mehdi")
    with pytest.raises(github.GitHubError):
        await workflow.submit_for_review(FakeSession(), 1, 7, author, "sum", False, title="fix(api): handle x")
    task.branch = "task/7"  # the rollback restored the old value
    await workflow.submit_for_review(FakeSession(), 1, 7, author, "sum", False, title="feat(api): handle y")
    assert task.branch == "feat/7-handle-y"
    assert head["branch"] == "feat/7-handle-y"


async def test_sensitive_files_close_the_gate_whatever_the_flag(monkeypatch):
    events = []
    task = SimpleNamespace(
        id=7, project_id=1, assignee_id=1, status=TaskStatus.in_progress, branch="task/7", worktree_path="/tmp/w",
        pr_number=12, pr_url="u", pr_title="old", acceptance_criteria=[], description="", review_round=1,
        sensitive=False, conversation_id=1, title="T", merge_ready_at=None, lead_reminded_at=None, reviewed_head=None,
    )
    gits = []

    async def get_task(*_):
        return task

    async def commits_ahead(*_):
        return 1

    async def git(*args, **__):
        gits.append(args)
        return "README.md\0backend/app/runner.py\0" if "--name-only" in args else ""

    async def noop(*_, **__):
        pass

    async def changes_pending(*_):
        return False

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "_changes_pending", changes_pending)
    monkeypatch.setattr(workflow, "_commits_ahead", commits_ahead)
    monkeypatch.setattr(workflow, "announce", noop)
    monkeypatch.setattr(workflow, "post_message", noop)
    monkeypatch.setattr(workflow, "emit_event", lambda *a, **k: events.append(a[2]))
    monkeypatch.setattr(workflow, "mode_process", lambda _: {"qa_gate": False, "security_gate": True})
    monkeypatch.setattr(github, "git", git)
    monkeypatch.setattr(workflow, "push_task_branch", noop)
    monkeypatch.setattr(github, "set_pull_request_title", noop)
    monkeypatch.setattr(github, "comment_pull_request", noop)

    await workflow.submit_for_review(
        FakeSession(), 1, 7, SimpleNamespace(id=1, name="Mehdi"), "sum", False, title="fix(api): handle x"
    )
    assert task.sensitive is True
    assert "sensitive_pr" in events
    diff = next(g for g in gits if "--name-only" in g)
    assert "--no-renames" in diff and "-z" in diff and diff[-1] == "origin/dev...origin/task/7"

    # Without security's approval the merge stays blocked
    class Sess:
        async def scalars(self, *_):
            return []

    monkeypatch.setattr(workflow, "mode_process", lambda _: {
        "qa_gate": False, "security_gate": True, "required_approvals": 0, "ci_required": False, "docs_required": False,
    })
    blockers = await workflow.merge_blockers(Sess(), SimpleNamespace(mode=None), task)
    assert "security has not approved this sensitive PR" in blockers


def _rebase_task(**over):
    base = dict(
        id=7, project_id=1, assignee_id=1, status=TaskStatus.in_progress, branch="task/7", worktree_path="/tmp/w",
        pr_number=12, pr_url="u", pr_title="old", acceptance_criteria=[], description="", review_round=2,
        sensitive=False, conversation_id=1, title="T", merge_ready_at="then", lead_reminded_at=None,
        reviewed_head="aaa",
    )
    base.update(over)
    return SimpleNamespace(**base)


async def _resubmit(monkeypatch, task, head, changes=False, pure=True):
    events = []

    async def get_task(*_):
        return task

    async def commits_ahead(*_):
        return 1

    async def git(*args, **__):
        return ""

    async def noop(*_, **__):
        pass

    async def changes_pending(*_):
        return changes

    async def pushed_head(*_):
        return head

    async def is_pure_rebase(*_):
        return pure

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "_changes_pending", changes_pending)
    monkeypatch.setattr(workflow, "_pushed_head", pushed_head)
    monkeypatch.setattr(workflow, "_is_pure_rebase", is_pure_rebase)
    monkeypatch.setattr(workflow, "_commits_ahead", commits_ahead)
    monkeypatch.setattr(workflow, "announce", noop)
    monkeypatch.setattr(workflow, "post_message", noop)
    monkeypatch.setattr(workflow, "emit_event", lambda *a, **k: events.append(a[2]))
    monkeypatch.setattr(workflow, "mode_process", lambda _: {"qa_gate": True, "security_gate": False})
    monkeypatch.setattr(github, "git", git)
    monkeypatch.setattr(workflow, "push_task_branch", noop)
    monkeypatch.setattr(github, "set_pull_request_title", noop)
    monkeypatch.setattr(github, "comment_pull_request", noop)
    await workflow.submit_for_review(
        FakeSession(), 1, 7, SimpleNamespace(id=1, name="Mehdi"), "sum", False, title="fix(api): handle x"
    )
    return events


async def test_pure_rebase_keeps_the_round_and_wakes_nobody(monkeypatch):
    task = _rebase_task()
    events = await _resubmit(monkeypatch, task, "aaa")
    assert events == []
    assert task.review_round == 2
    assert task.merge_ready_at is None
    assert task.status == TaskStatus.review


async def test_changed_content_starts_a_new_round(monkeypatch):
    task = _rebase_task()
    events = await _resubmit(monkeypatch, task, "bbb", pure=False)
    assert events == ["review_requested", "pr_ready"]
    assert task.review_round == 3
    assert task.merge_ready_at is None
    assert task.reviewed_head == "bbb"


async def test_requested_changes_always_start_a_new_round(monkeypatch):
    task = _rebase_task()  # a task run always starts in_progress; the round holds the changes verdict
    events = await _resubmit(monkeypatch, task, "aaa", changes=True)
    assert task.review_round == 3
    assert "review_requested" in events


async def test_new_sensitive_gate_starts_a_new_round(monkeypatch):
    task = _rebase_task()
    monkeypatch.setattr(workflow, "touches_sensitive_paths", lambda _: True)
    events = await _resubmit(monkeypatch, task, "aaa")
    assert task.review_round == 3 and task.sensitive is True
    assert "review_requested" in events


async def test_pure_rebase_with_real_git(tmp_path, monkeypatch):
    import subprocess

    def run(cwd, *a):
        return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout

    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    run(clone, "config", "user.email", "a@b.c")
    run(clone, "config", "user.name", "t")
    run(clone, "checkout", "-q", "-b", "dev")
    ctx = "    if not is_admin(user):\n        raise Forbidden\n    load()\n"
    original = f"def admin_view():\n{ctx}\n\ndef public_view():\n{ctx}\n"
    (clone / "a.py").write_text(original)
    (clone / "b.txt").write_text("1\n")
    run(clone, "add", ".")
    run(clone, "commit", "-qm", "init")
    run(clone, "push", "-q", "origin", "dev")

    def feature(content, base="origin/dev"):
        run(clone, "checkout", "-q", "-B", "task", base)
        (clone / "a.py").write_text(content)
        run(clone, "commit", "-qam", "work")
        run(clone, "push", "-qf", "origin", "task")
        run(clone, "fetch", "-q")

    async def real_git(cwd, *args, **_):
        p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
        if p.returncode:
            raise github.GitHubError(p.stderr)
        return p.stdout

    monkeypatch.setattr(github, "git", real_git)
    monkeypatch.setattr(workflow, "repo_dir", lambda _: clone)
    project = SimpleNamespace(default_branch="dev")
    task = SimpleNamespace(id=1, branch="task", reviewed_head=None)

    async def check():
        head = await workflow._pushed_head(project, task)
        return await workflow._is_pure_rebase(project, task, head)

    # The reviewed hunk lands in admin_view, after its guard
    first = original.replace("load()\n\n\ndef public", "load()\n    audit()\n\n\ndef public", 1)
    feature(first)
    task.reviewed_head = await workflow._pushed_head(project, task)
    await workflow._keep_reviewed_head(project, task, task.reviewed_head)
    assert await check()  # the very same commit

    # The base moves (same file, elsewhere, and another file) and the branch is rebased: kept
    run(clone, "checkout", "-q", "dev")
    (clone / "b.txt").write_text("2\n")
    (clone / "a.py").write_text(original + "# footer\n")
    run(clone, "commit", "-qam", "base moved")
    run(clone, "push", "-q", "origin", "dev")
    run(clone, "checkout", "-q", "task")
    run(clone, "rebase", "-q", "dev")
    run(clone, "push", "-qf", "origin", "task")
    run(clone, "fetch", "-q")
    assert await check()

    # The reviewed commit is gone after the force-push, only the ref keeps it
    run(clone, "reflog", "expire", "--expire=now", "--all")
    run(clone, "gc", "-q", "--prune=now")
    assert await check()

    # The same hunk moved into public_view (identical context): a patch-id would not see it
    moved = (clone / "a.py").read_text().replace("    audit()\n", "")
    moved = moved.replace("load()\n\n# footer", "load()\n    audit()\n\n# footer")
    feature(moved, base="dev")
    assert not await check()

    # Indentation only, and a content change
    feature((clone / "a.py").read_text().replace("    audit()", "        audit()"), base="dev")
    assert not await check()
    feature((clone / "a.py").read_text().replace("audit()", "evil()"), base="dev")
    assert not await check()

    # Unknown reviewed commit: fail closed
    task.reviewed_head = "0" * 40
    assert not await check()


@pytest.mark.parametrize("clone_branch, adopted", [("fix/7-handle-x", True), ("feat/99-other", False)])
async def test_resubmission_after_a_rolled_back_submission_reuses_the_open_pr(monkeypatch, clone_branch, adopted):
    """The PR was opened, then the submission failed and the database rolled back: a retry with another
    title must not rename the branch and open a second PR for the same work (#372). A clone sitting on
    another task's branch must never adopt that task's PR."""
    task = SimpleNamespace(
        id=7, project_id=1, assignee_id=1, status=TaskStatus.in_progress, branch="task/7", worktree_path="/tmp/w",
        pr_number=None, pr_url=None, pr_title=None, acceptance_criteria=[], description="", review_round=0,
        sensitive=False, conversation_id=1, title="T", merge_ready_at=None, lead_reminded_at=None, reviewed_head=None,
    )
    opened, renamed, titles = [], [], []

    async def noop(*_, **__):
        pass

    async def get_task(*_):
        return task

    async def commits_ahead(*_):
        return 1

    async def git(path, *args, **__):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return f"{clone_branch}\n"  # renamed and pushed by the first, rolled back, attempt
        if args[0] == "branch":
            renamed.append(args)
        return ""

    async def find_pr(repo, head, base):
        return {"number": 3, "html_url": "u"} if head == clone_branch else None

    async def open_pr(repo, **kw):
        opened.append(kw)
        return {"number": 4, "html_url": "u2"}

    async def set_title(repo, number, title):
        titles.append((number, title))

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "_commits_ahead", commits_ahead)
    monkeypatch.setattr(workflow, "announce", noop)
    monkeypatch.setattr(workflow, "post_message", noop)
    monkeypatch.setattr(workflow, "emit_event", lambda *_, **__: None)
    monkeypatch.setattr(workflow, "mode_process", lambda _: {"qa_gate": False, "security_gate": False})
    monkeypatch.setattr(github, "git", git)
    monkeypatch.setattr(worktrees, "git", git)
    monkeypatch.setattr(workflow, "push_task_branch", noop)
    monkeypatch.setattr(github, "find_pull_request", find_pr)
    monkeypatch.setattr(github, "open_pull_request", open_pr)
    monkeypatch.setattr(github, "set_pull_request_title", set_title)
    monkeypatch.setattr(github, "comment_pull_request", noop)

    await workflow.submit_for_review(
        FakeSession(), 1, 7, SimpleNamespace(id=1, name="Mehdi"), "sum", False, title="feat(api): handle y"
    )
    if adopted:
        assert opened == [] and renamed == []
        assert task.pr_number == 3 and task.branch == "fix/7-handle-x"
        assert titles == [(3, "feat(api): handle y")]
    else:
        assert task.pr_number == 4 and task.branch == "feat/7-handle-y" and titles == []
