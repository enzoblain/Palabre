"""Merge-ready wakeups, the single reminder, and the announcements in the task's conversation."""

from datetime import UTC, datetime, timedelta

import pytest

from app import github, workflow
from app.models import Message, Task
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

    monkeypatch.setattr(workflow, "merge_blockers", blockers)
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
