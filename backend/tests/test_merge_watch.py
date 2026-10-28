"""Merge-ready wakeups, the single reminder, and the announcements in the task's conversation."""

from datetime import UTC, datetime, timedelta

import pytest

from app import github, workflow
from app.models import Message, Task, TaskStatus
from app.orchestrator import merge_watch

from .conftest import make_project, make_task


class WatchSession:
    def __init__(self, tasks, project):
        self.tasks, self.project, self.added, self.commits = tasks, project, [], 0

    async def scalars(self, _query):
        return self.tasks

    async def get(self, _model, _pk):
        return self.project

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


@pytest.fixture
def watch(project, monkeypatch):
    monkeypatch.setattr(merge_watch, "_last_check", {})
    state = type("S", (), {"blockers": []})()

    async def blockers(_s, _project, _task):
        return state.blockers

    async def pull_request(_repo, _number):
        return state.pr

    async def team_conversation(_s, _pid):
        return 3

    monkeypatch.setattr(workflow, "merge_blockers", blockers)
    monkeypatch.setattr(github, "get_pull_request", pull_request)
    monkeypatch.setattr(merge_watch, "team_conversation_id", team_conversation)
    state.pr = {"head": {"sha": "abc"}, "base": {"ref": "dev"}, "mergeable_state": "clean"}
    return state


def events_of(session, type_):
    return [e for e in session.added if getattr(e, "type", None) == type_]


def reviewable(**fields):
    return make_task(**({"merge_ready_at": None, "lead_reminded_at": None, "project_id": 1, "pr_url": "https://github.com/acme/app/pull/42"} | fields))


async def test_mergeable_task_wakes_the_lead(watch, project):
    task = reviewable()
    s = WatchSession([task], project)
    await merge_watch.watch_mergeable_tasks(s)
    [event] = events_of(s, "pr_approved")
    assert event.target_role == "lead" and event.payload["task_id"] == task.id
    assert task.merge_ready_at is not None


async def test_blocked_task_wakes_nobody(watch, project):
    watch.blockers = ["CI is running"]
    s = WatchSession([reviewable()], project)
    await merge_watch.watch_mergeable_tasks(s)
    assert not s.added


async def test_lead_is_woken_only_once(watch, project):
    task = reviewable()
    s = WatchSession([task], project)
    await merge_watch.watch_mergeable_tasks(s)
    await merge_watch.watch_mergeable_tasks(s)
    assert len(events_of(s, "pr_approved")) == 1


async def test_reminder_after_the_delay_then_never_again(watch, project, monkeypatch):
    monkeypatch.setattr(merge_watch.settings, "merge_reminder_minutes", 10)
    task = reviewable(merge_ready_at=datetime.now(UTC) - timedelta(minutes=11))
    s = WatchSession([task], project)
    await merge_watch.watch_mergeable_tasks(s)
    await merge_watch.watch_mergeable_tasks(s)
    [event] = events_of(s, "pr_approved")
    assert event.target_role == "lead" and "reminder" in event.payload["reviewer"]


async def test_no_reminder_before_the_delay(watch, project):
    task = reviewable(merge_ready_at=datetime.now(UTC) - timedelta(minutes=2))
    s = WatchSession([task], project)
    await merge_watch.watch_mergeable_tasks(s)
    assert not s.added


async def test_broken_rule_resets_readiness(watch, project):
    watch.blockers = ["CI failed"]
    task = reviewable(merge_ready_at=datetime.now(UTC) - timedelta(minutes=30))
    s = WatchSession([task], project)
    await merge_watch.watch_mergeable_tasks(s)
    assert task.merge_ready_at is None and not s.added


async def test_announce_posts_a_system_line_with_the_link():
    task = make_task(title="Demo", conversation_id=7, pr_url="https://github.com/acme/app/pull/42")
    s = WatchSession([], make_project())
    await workflow.announce(s, task, "Merged")
    [msg] = s.added
    assert isinstance(msg, Message)
    assert msg.conversation_id == 7 and msg.employee_id is None and msg.author_name == "Palabre"
    assert msg.content.startswith("Merged") and "pull/42" in msg.content


async def test_mark_merge_ready_is_idempotent(project):
    task = reviewable()
    s = WatchSession([], project)
    await workflow.mark_merge_ready(s, task, "Karim")
    await workflow.mark_merge_ready(s, task, "Karim")
    assert len(events_of(s, "pr_approved")) == 1


async def test_a_task_whose_rules_cannot_be_checked_does_not_stop_the_others(watch, project, monkeypatch):
    broken, fine = reviewable(), reviewable()

    async def blockers(_s, _project, task):
        if task is broken:
            raise github.GitHubError("boom")
        return []

    monkeypatch.setattr(workflow, "merge_blockers", blockers)
    s = WatchSession([broken, fine], project)
    await merge_watch.watch_mergeable_tasks(s)
    [event] = events_of(s, "pr_approved")
    assert event.payload["task_id"] == fine.id and s.commits == 1


async def test_system_line_is_not_a_boss_message():
    s = WatchSession([], make_project())
    await workflow.announce(s, make_task(title="Demo", conversation_id=7, pr_url=None), "Merged")
    assert s.added[0].is_system is True


class CiGitHub:
    """GitHub mocked: the release PR, production's head and the CI answer of each commit."""

    def __init__(self, monkeypatch, checks, pr_sha="aaa", head="bbb"):
        self.checks, self.pr_sha, self.head = checks, pr_sha, head

        async def resolve(_repo, _branch):
            return "main"

        async def find(_repo, _head, _base):
            return {"number": 9, "html_url": "https://github.com/acme/app/pull/9", "head": {"sha": self.pr_sha}} if self.pr_sha else None

        async def branch_head(_repo, _branch):
            return self.head

        async def commit_checks(_repo, sha):
            return self.checks[sha]

        monkeypatch.setattr(github, "resolve_branch", resolve)
        monkeypatch.setattr(github, "find_pull_request", find)
        monkeypatch.setattr(github, "branch_head", branch_head)
        monkeypatch.setattr(github, "commit_checks", commit_checks)


@pytest.fixture
def ci_project(monkeypatch):
    monkeypatch.setattr(merge_watch, "_last_release_check", {})
    monkeypatch.setattr(merge_watch, "team_conversation_id", lambda _s, _pid: _async(3))
    project = make_project()
    project.kind, project.default_branch = "company", "dev"
    project.release_ci_sha = project.main_ci_sha = None
    project.main_ci_watch = False
    return project


async def _async(value):
    return value


async def test_release_ci_green_wakes_the_lead_once(ci_project, monkeypatch):
    CiGitHub(monkeypatch, {"aaa": None})
    s = WatchSession([ci_project], ci_project)
    await merge_watch.watch_release_ci(s)
    merge_watch._last_release_check.clear()
    await merge_watch.watch_release_ci(s)
    [event] = events_of(s, "release_ci")
    assert event.target_role == "lead" and event.payload["result"] == "green" and event.payload["pr_number"] == 9
    [line] = [m for m in s.added if isinstance(m, Message)]
    assert line.conversation_id == 3 and line.is_system and "green" in line.content


async def test_release_ci_red_lists_the_failed_checks(ci_project, monkeypatch):
    CiGitHub(monkeypatch, {"aaa": "CI failed: backend, front"})
    s = WatchSession([ci_project], ci_project)
    await merge_watch.watch_release_ci(s)
    [event] = events_of(s, "release_ci")
    assert "backend, front" in event.payload["result"]


async def test_release_ci_still_running_wakes_nobody_then_a_new_sha_wakes_again(ci_project, monkeypatch):
    gh = CiGitHub(monkeypatch, {"aaa": "CI still running: backend", "ccc": None})
    s = WatchSession([ci_project], ci_project)
    await merge_watch.watch_release_ci(s)
    assert not s.added
    gh.checks["aaa"] = None
    merge_watch._last_release_check.clear()
    await merge_watch.watch_release_ci(s)
    gh.pr_sha = "ccc"
    merge_watch._last_release_check.clear()
    await merge_watch.watch_release_ci(s)
    assert len(events_of(s, "release_ci")) == 2


async def test_main_ci_is_followed_after_merge_release_until_it_ends(ci_project, monkeypatch):
    CiGitHub(monkeypatch, {"bbb": "no CI checks reported"}, pr_sha=None)
    ci_project.main_ci_watch = True
    s = WatchSession([ci_project], ci_project)
    await merge_watch.watch_release_ci(s)
    assert not s.added and ci_project.main_ci_watch
    CiGitHub(monkeypatch, {"bbb": "CI failed: backend"}, pr_sha=None)
    merge_watch._last_release_check.clear()
    await merge_watch.watch_release_ci(s)
    [event] = events_of(s, "main_ci")
    assert "red" in event.payload["result"] and not ci_project.main_ci_watch and ci_project.main_ci_sha == "bbb"
    merge_watch._last_release_check.clear()
    await merge_watch.watch_release_ci(s)
    assert len(events_of(s, "main_ci")) == 1


async def test_github_error_is_logged_not_raised(ci_project, monkeypatch):
    async def boom(*_a):
        raise github.GitHubError("boom")

    monkeypatch.setattr(github, "resolve_branch", boom)
    s = WatchSession([ci_project], ci_project)
    await merge_watch.watch_release_ci(s)
    assert not s.added and s.commits == 1


def stuck_task(**fields):
    return reviewable(title="Demo", assignee_id=5, status=TaskStatus.review, submitted_at=datetime.now(UTC) - timedelta(minutes=30), **({"stuck_sha": None} | fields))


async def test_conflicting_pr_goes_back_to_its_dev_once_per_sha(watch, project):
    watch.pr["mergeable_state"] = "dirty"
    watch.blockers = ["no CI checks reported"]
    task = stuck_task()
    s = WatchSession([task], project)
    await merge_watch.watch_mergeable_tasks(s)
    merge_watch._last_check.clear()
    await merge_watch.watch_mergeable_tasks(s)
    [event] = events_of(s, "pr_blocked")
    assert event.target_employee_id == 5 and "conflict with dev: rebase" in event.payload["problem"]
    assert task.status == TaskStatus.changes_requested and task.stuck_sha == "abc"
    [line] = [m for m in s.added if isinstance(m, Message)]
    assert "sent back" in line.content


async def test_a_new_head_sha_wakes_the_dev_again(watch, project):
    watch.pr["mergeable_state"] = "dirty"
    task = stuck_task(stuck_sha="old")
    s = WatchSession([task], project)
    await merge_watch.watch_mergeable_tasks(s)
    assert len(events_of(s, "pr_blocked")) == 1 and task.stuck_sha == "abc"


async def test_missing_ci_goes_back_only_after_the_delay(watch, project):
    watch.blockers = ["no CI checks reported"]
    recent = stuck_task()
    recent.submitted_at = datetime.now(UTC) - timedelta(minutes=2)
    s = WatchSession([recent], project)
    await merge_watch.watch_mergeable_tasks(s)
    assert not events_of(s, "pr_blocked")
    late = stuck_task()
    s = WatchSession([late], project)
    await merge_watch.watch_mergeable_tasks(s)
    [event] = events_of(s, "pr_blocked")
    assert "no CI reported" in event.payload["problem"]


async def test_red_ci_on_an_approved_task_lists_the_failing_checks(watch, project):
    watch.blockers = ["CI failed: lint, tests"]
    s = WatchSession([stuck_task()], project)
    await merge_watch.watch_mergeable_tasks(s)
    [event] = events_of(s, "pr_blocked")
    assert event.payload["problem"] == "CI failed: lint, tests"


async def test_red_ci_waits_for_the_reviews(watch, project):
    watch.blockers = ["CI failed: lint", "0/1 reviewer approval(s)"]
    s = WatchSession([stuck_task()], project)
    await merge_watch.watch_mergeable_tasks(s)
    assert not s.added


async def test_running_ci_is_left_alone(watch, project):
    watch.blockers = ["CI still running: tests"]
    s = WatchSession([stuck_task()], project)
    await merge_watch.watch_mergeable_tasks(s)
    assert not s.added
