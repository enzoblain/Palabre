"""workflow.merge_blockers: each merge rule, passing and failing."""

import pytest

from app import workflow
from app.errors import ErrorCode, WorkflowError
from app.models import Verdict

from .conftest import FakeSession, make_employee, make_project, make_review, make_task


async def blockers(project, task, *reviews):
    return await workflow.merge_blockers(FakeSession(list(reviews)), project, task)


# --- Reviewer approvals ------------------------------------------------------------


async def test_one_reviewer_approval_is_enough(project, task, reviewer, process, fake_github):
    process(required_approvals=1)
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


async def test_no_review_blocks(project, task, process, fake_github):
    process(required_approvals=1)
    assert await blockers(project, task) == ["0/1 reviewer approval(s)"]


async def test_not_enough_approvals(project, task, reviewer, process, fake_github):
    process(required_approvals=2)
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == ["1/2 reviewer approval(s)"]


async def test_two_distinct_approvals_pass(project, task, reviewer, process, fake_github):
    process(required_approvals=2)
    other = make_employee("Léa", "reviewer")
    reviews = [make_review(reviewer, Verdict.approve), make_review(other, Verdict.approve)]
    assert await blockers(project, task, *reviews) == []


async def test_approval_from_a_non_reviewer_does_not_count(project, task, process, fake_github):
    process(required_approvals=1)
    dev = make_employee("Nina", "backend_dev")
    assert await blockers(project, task, make_review(dev, Verdict.approve)) == ["0/1 reviewer approval(s)"]


async def test_changes_requested_blocks(project, task, reviewer, process, fake_github):
    process()
    result = await blockers(project, task, make_review(reviewer, Verdict.changes))
    assert "Karim requested changes" in result


async def test_latest_verdict_of_a_reviewer_wins(project, task, reviewer, process, fake_github):
    process()
    reviews = [make_review(reviewer, Verdict.changes), make_review(reviewer, Verdict.approve)]
    assert await blockers(project, task, *reviews) == []


async def test_a_comment_does_not_cancel_an_approval(project, task, reviewer, process, fake_github):
    process()
    reviews = [make_review(reviewer, Verdict.approve), make_review(reviewer, Verdict.comment)]
    assert await blockers(project, task, *reviews) == []


# --- QA ----------------------------------------------------------------------------


async def test_qa_gate_passes_with_qa_approval(project, task, reviewer, qa, process, fake_github):
    process(qa_gate=True)
    reviews = [make_review(reviewer, Verdict.approve), make_review(qa, Verdict.approve)]
    assert await blockers(project, task, *reviews) == []


async def test_qa_gate_blocks_without_qa_approval(project, task, reviewer, process, fake_github):
    process(qa_gate=True)
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == ["QA has not approved"]


async def test_qa_not_required_when_gate_is_off(project, task, reviewer, process, fake_github):
    process(qa_gate=False)
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


# --- Security ----------------------------------------------------------------------


async def test_security_gate_passes_with_security_approval(project, task, reviewer, security, process, fake_github):
    process(security_gate=True)
    task.sensitive = True
    reviews = [make_review(reviewer, Verdict.approve), make_review(security, Verdict.approve)]
    assert await blockers(project, task, *reviews) == []


async def test_security_gate_blocks_sensitive_task_without_security(project, task, reviewer, process, fake_github):
    process(security_gate=True)
    task.sensitive = True
    result = await blockers(project, task, make_review(reviewer, Verdict.approve))
    assert result == ["security has not approved this sensitive PR"]


async def test_security_gate_ignores_non_sensitive_task(project, task, reviewer, process, fake_github):
    process(security_gate=True)
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


async def test_security_not_required_when_gate_is_off(project, task, reviewer, process, fake_github):
    process(security_gate=False)
    task.sensitive = True
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


# --- CI ----------------------------------------------------------------------------


async def test_ci_green_passes(project, task, reviewer, process, fake_github):
    process(ci_required=True)
    fake_github.ci = None
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


async def test_ci_failure_blocks(project, task, reviewer, process, fake_github):
    process(ci_required=True)
    fake_github.ci = "CI failed: tests"
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == ["CI failed: tests"]


async def test_ci_ignored_when_not_required(project, task, reviewer, process, fake_github):
    process(ci_required=False)
    fake_github.ci = "CI failed: tests"
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


async def test_ci_skipped_without_pull_request(project, task, reviewer, process, fake_github):
    process(ci_required=True)
    task.pr_number = None
    fake_github.ci = "CI failed: tests"
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


# --- Docs --------------------------------------------------------------------------


async def test_readme_updated_passes(project, task, reviewer, process, fake_github):
    process(docs_required=True)
    fake_github.changed_files = ["app/x.py", "frontend/README.md"]
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


async def test_docs_folder_passes(project, task, reviewer, process, fake_github):
    process(docs_required=True)
    fake_github.changed_files = ["app/x.py", "docs/usage.md"]
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


async def test_readme_match_is_case_insensitive(project, task, reviewer, process, fake_github):
    process(docs_required=True)
    fake_github.changed_files = ["readme.md"]
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


async def test_missing_docs_blocks_and_the_changelog_does_not_count(project, task, reviewer, process, fake_github):
    process(docs_required=True)
    fake_github.changed_files = ["app/x.py", "CHANGELOG.md"]
    result = await blockers(project, task, make_review(reviewer, Verdict.approve))
    assert result == ["the README or docs/ were not updated"]


async def test_docs_ignored_when_not_required(project, task, reviewer, process, fake_github):
    process(docs_required=False)
    fake_github.changed_files = ["app/x.py"]
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []
    assert fake_github.git_calls == []


# --- Real catalog ------------------------------------------------------------------


async def test_startup_mode_only_needs_one_approval(project, task, reviewer, fake_github):
    project.mode = "startup"
    assert await blockers(project, task, make_review(reviewer, Verdict.approve)) == []


async def test_multinational_task_touching_the_readme_is_not_blocked_on_docs(project, task, fake_github):
    project.mode = "multinational"
    fake_github.changed_files = ["app/x.py", "README.md"]
    assert "the README or docs/ were not updated" not in await blockers(project, task)


async def test_multinational_mode_stacks_every_gate(project, task, fake_github):
    project.mode = "multinational"
    task.sensitive = True
    fake_github.ci = "CI failed"
    fake_github.changed_files = ["app/x.py"]
    assert await blockers(project, task) == [
        "0/2 reviewer approval(s)",
        "QA has not approved",
        "security has not approved this sensitive PR",
        "CI failed",
        "the README or docs/ were not updated",
    ]


# --- Outdated opinions -------------------------------------------------------------


async def test_changes_on_a_previous_round_no_longer_blocks(project, reviewer, process, fake_github):
    process()
    task = make_task(review_round=2)
    reviews = [make_review(reviewer, Verdict.changes, round=1), make_review(reviewer, Verdict.approve, round=2)]
    assert await blockers(project, task, *reviews) == []


async def test_changes_on_an_old_head_is_named_and_does_not_block_as_changes(project, reviewer, process, fake_github):
    process()
    task = make_task(review_round=2, reviewed_head="new")
    result = await blockers(project, task, make_review(reviewer, Verdict.changes, round=1, head_sha="old"))
    assert "Karim requested changes" not in result
    assert any("Karim" in b and "outdated" in b and "must review" in b for b in result)


async def test_approval_on_an_old_head_does_not_count(project, reviewer, process, fake_github):
    process(required_approvals=1)
    task = make_task(reviewed_head="new")
    result = await blockers(project, task, make_review(reviewer, Verdict.approve, head_sha="old"))
    assert "0/1 reviewer approval(s)" in result
    assert any("outdated" in b for b in result)


async def test_opinion_on_the_current_head_counts(project, reviewer, process, fake_github):
    process()
    task = make_task(reviewed_head="abc")
    assert await blockers(project, task, make_review(reviewer, Verdict.approve, head_sha="abc")) == []


async def test_stale_qa_is_named(project, reviewer, qa, process, fake_github):
    process(qa_gate=True)
    task = make_task(review_round=2)
    reviews = [make_review(reviewer, Verdict.approve, round=2), make_review(qa, Verdict.approve, round=1)]
    result = await blockers(project, task, *reviews)
    assert "QA has not approved" in result
    assert any("Samuel" in b and "outdated" in b for b in result)


async def test_review_on_an_old_head_is_refused(reviewer, monkeypatch):
    task = make_task(reviewed_head="b" * 40)

    class Sess:
        async def get(self, *_):
            return make_project()

    async def get_task(*_):
        return task

    monkeypatch.setattr(workflow, "get_task", get_task)
    with pytest.raises(WorkflowError, match="PR head is now"):
        await workflow.review_task(Sess(), 1, task.id, reviewer, "changes", "x", head_sha="a" * 8)


class RecordingSession:
    def __init__(self):
        self.added = []

    async def get(self, *_):
        return make_project()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass


def patch_review_flow(monkeypatch, task):
    async def get_task(*_):
        return task

    async def noop(*_, **__):
        pass

    async def no_blockers(*_):
        return []

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "announce", noop)
    monkeypatch.setattr(workflow, "wake_lead", lambda *_: None)
    monkeypatch.setattr(workflow, "wake_dev", noop)
    monkeypatch.setattr(workflow, "mark_merge_ready", noop)
    monkeypatch.setattr(workflow, "merge_blockers", no_blockers)


async def test_review_with_a_matching_short_sha_is_recorded(reviewer, monkeypatch):
    task = make_task(reviewed_head="abcdef0123456789" * 2 + "abcdef01", pr_number=None)
    patch_review_flow(monkeypatch, task)
    session = RecordingSession()
    assert await workflow.review_task(session, 1, task.id, reviewer, "approve", "ok", head_sha="abcdef01") == []
    assert session.added[0].head_sha == task.reviewed_head


async def test_review_with_a_too_short_sha_is_refused(reviewer, monkeypatch):
    task = make_task(reviewed_head="abcdef0123456789", pr_number=None)
    patch_review_flow(monkeypatch, task)
    with pytest.raises(WorkflowError) as error:
        await workflow.review_task(RecordingSession(), 1, task.id, reviewer, "approve", "ok", head_sha="a")
    assert error.value.code == ErrorCode.INVALID_HEAD_SHA


async def test_review_on_an_old_head_has_a_dedicated_code(reviewer, monkeypatch):
    task = make_task(reviewed_head="b" * 40, pr_number=None)
    patch_review_flow(monkeypatch, task)
    with pytest.raises(WorkflowError) as error:
        await workflow.review_task(RecordingSession(), 1, task.id, reviewer, "changes", "x", head_sha="a" * 8)
    assert error.value.code == ErrorCode.STALE_REVIEW_HEAD


async def test_changes_pending_ignores_a_stale_changes_request(reviewer):
    task = make_task(reviewed_head="new")
    stale = make_review(reviewer, Verdict.changes, head_sha="old")
    assert not await workflow._changes_pending(FakeSession([stale]), task)


async def test_changes_pending_sees_a_current_changes_request(reviewer):
    task = make_task(reviewed_head="new")
    current = make_review(reviewer, Verdict.changes, head_sha="new")
    assert await workflow._changes_pending(FakeSession([current]), task)
