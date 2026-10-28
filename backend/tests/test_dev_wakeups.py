"""A task sent back or reassigned wakes its dev once, the watchdog nudges then alerts, a refused merge is retried."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import github, workflow
from app.models import TaskStatus
from app.orchestrator import merge_watch
from app.services import WorkflowError

from .conftest import make_employee, make_project, make_task


class Session:
    """scalar() and scalars() serve queued answers in call order (the queries are ignored)."""

    def __init__(self, *, scalar=(), scalars=()):
        self.scalar_results, self.scalars_results = list(scalar), list(scalars)
        self.added, self.commits = [], 0

    async def scalar(self, _query):
        return self.scalar_results.pop(0) if self.scalar_results else None

    async def scalars(self, _query):
        return self.scalars_results.pop(0) if self.scalars_results else []

    async def get(self, *_):
        return make_project()

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


def events(s, type_):
    return [e for e in s.added if getattr(e, "type", None) == type_]


def dev_task(**fields):
    return make_task(**({"status": TaskStatus.todo, "assignee_id": 7} | fields))


async def test_wake_dev_targets_the_assignee_with_the_task():
    task, s = dev_task(unstarted_nudges=1), Session()
    assert await workflow.wake_dev(s, task, "task_nudge", {"why": "back in todo"})
    [event] = events(s, "task_nudge")
    assert event.target_employee_id == 7 and event.payload == {"task_id": task.id, "why": "back in todo"}
    assert task.unstarted_nudges == 0


async def test_wake_dev_without_assignee_does_nothing():
    s = Session()
    assert not await workflow.wake_dev(s, make_task(assignee_id=None), "task_nudge")
    assert not s.added


async def test_wake_dev_skips_a_running_wakeup_when_deduping():
    s = Session(scalar=[123])
    assert not await workflow.wake_dev(s, dev_task(), "task_nudge", dedupe=True)
    assert not s.added


async def test_wake_dev_skips_a_queued_event_when_deduping():
    task = dev_task()
    queued = SimpleNamespace(type="task_assigned", payload={"task_id": task.id})
    s = Session(scalars=[[queued]])
    assert not await workflow.wake_dev(s, task, "task_nudge", dedupe=True)


async def test_wake_dev_without_dedupe_always_wakes():
    s = Session(scalar=[123])
    assert await workflow.wake_dev(s, dev_task(), "changes_requested")
    assert events(s, "changes_requested")


@pytest.fixture
def flow(monkeypatch):
    task = dev_task(project_id=1, depends_on=[], title="T", pr_number=None, pr_url=None, assignee=None)
    employee = make_employee("Malik", "backend")
    state = SimpleNamespace(task=task, employee=employee)

    async def get_task(_s, _pid, _tid):
        return state.task

    async def find_employee(_s, _pid, _name):
        return state.employee

    async def clean_up(*_):
        pass

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow, "find_employee", find_employee)
    monkeypatch.setattr(workflow, "clean_up_task", clean_up)
    return state


async def test_assign_changes_the_assignee_and_wakes_the_new_dev(flow):
    s = Session(scalar=[123])  # The previous dev still has a run: it must not block the new one
    task = await workflow.assign_task(s, 1, flow.task.id, "Malik")
    assert task.assignee_id == flow.employee.id and task.assignee is flow.employee
    [event] = events(s, "task_assigned")
    assert event.target_employee_id == flow.employee.id


async def test_assign_to_the_same_dev_twice_does_not_double_wake(flow):
    flow.task.assignee_id = flow.employee.id
    s = Session(scalar=[123])
    await workflow.assign_task(s, 1, flow.task.id, "Malik")
    assert not s.added


async def test_back_to_todo_with_a_pr_asks_for_a_rebase(flow):
    flow.task.status, flow.task.pr_number = TaskStatus.review, 42
    s = Session()
    await workflow.update_task(
        s, 1, flow.task.id, title=None, description=None, acceptance_criteria=None, depends_on=None, status="todo"
    )
    [event] = events(s, "task_nudge")
    assert "rebase" in event.payload["why"] and flow.task.status == TaskStatus.todo


async def test_back_to_todo_waiting_for_dependencies_wakes_nobody(flow):
    flow.task.depends_on = [99]
    s = Session(scalars=[[TaskStatus.todo]])
    await workflow.update_task(
        s, 1, flow.task.id, title=None, description=None, acceptance_criteria=None, depends_on=None, status="todo"
    )
    assert not s.added


async def test_refused_merge_while_ci_runs_is_remembered(flow, monkeypatch):
    flow.task.status, flow.task.pr_number, flow.task.pr_title = TaskStatus.review, 42, "feat: x"

    async def blockers(*_):
        return ["CI still running: tests"]

    monkeypatch.setattr(workflow, "merge_blockers", blockers)
    s = Session()
    with pytest.raises(WorkflowError):
        await workflow.merge_task(s, 1, flow.task.id, None)
    assert flow.task.merge_retry_at is not None and s.commits == 1


# --- Watchdog and CI retry ---------------------------------------------------------------


@pytest.fixture
def watch(monkeypatch):
    monkeypatch.setattr(merge_watch, "_last_unstarted_check", {})
    monkeypatch.setattr(merge_watch, "_last_check", {})
    monkeypatch.setattr(merge_watch, "_ci_seen", {})
    monkeypatch.setattr(workflow, "_lead_pending", {})


def waiting(**fields):
    return dev_task(**({"status": TaskStatus.changes_requested} | fields))


# scalar() answers, in order: dev busy?, last run, last wakeup
async def test_watchdog_nudges_the_dev_once_then_alerts_the_lead(watch):
    task = waiting()
    s = Session(scalars=[[task]])
    await merge_watch.watch_unstarted_tasks(s)
    [nudge] = events(s, "task_nudge")
    assert nudge.target_employee_id == 7 and task.unstarted_nudges == 1

    merge_watch._last_unstarted_check.clear()
    s2 = Session(scalars=[[task]])
    await merge_watch.watch_unstarted_tasks(s2)
    [alert] = events(s2, "task_idle")
    assert alert.target_role == "lead" and task.unstarted_nudges == 2 and not events(s2, "task_nudge")


async def test_watchdog_leaves_a_task_with_a_recent_run_alone(watch):
    task = waiting()
    s = Session(scalars=[[task]], scalar=[None, datetime.now(UTC) - timedelta(minutes=1), None])
    await merge_watch.watch_unstarted_tasks(s)
    assert not s.added


async def test_watchdog_leaves_a_busy_dev_alone(watch):
    s = Session(scalars=[[waiting()]], scalar=[123])
    await merge_watch.watch_unstarted_tasks(s)
    assert not s.added


async def test_watchdog_ignores_a_task_waiting_for_dependencies(watch):
    task = waiting(depends_on=[99])
    s = Session(scalars=[[task], [TaskStatus.in_progress]])
    await merge_watch.watch_unstarted_tasks(s)
    assert not s.added


@pytest.fixture
def ci(monkeypatch, watch):
    state = SimpleNamespace(blockers=[])

    async def blockers(*_):
        return state.blockers

    async def pull_request(*_):
        return {"head": {"sha": "abc"}, "base": {"ref": "dev"}, "mergeable_state": "clean"}

    async def team_conversation(*_):
        return 3

    monkeypatch.setattr(workflow, "merge_blockers", blockers)
    monkeypatch.setattr(github, "get_pull_request", pull_request)
    monkeypatch.setattr(merge_watch, "team_conversation_id", team_conversation)
    return state


def refused(**fields):
    return make_task(
        merge_ready_at=None, lead_reminded_at=None, project_id=1, pr_url="u", stuck_sha=None,
        submitted_at=None, merge_retry_at=datetime.now(UTC), **fields,
    )  # fmt: skip


async def test_lead_is_woken_when_the_ci_ends_after_a_refused_merge(ci):
    ci.blockers = ["CI failed: tests", "missing approval"]
    task = refused()
    s = Session(scalars=[[task]])
    await merge_watch.watch_mergeable_tasks(s)
    [event] = events(s, "merge_retry")
    assert event.target_role == "lead" and "CI failed" in event.payload["result"]
    assert task.merge_retry_at is None


async def test_lead_is_not_woken_while_the_ci_still_runs(ci):
    ci.blockers = ["CI still running: tests"]
    task = refused()
    s = Session(scalars=[[task]])
    await merge_watch.watch_mergeable_tasks(s)
    assert not events(s, "merge_retry") and task.merge_retry_at is not None


async def test_green_ci_wakes_the_lead_once_as_mergeable(ci):
    task = refused()
    s = Session(scalars=[[task]])
    await merge_watch.watch_mergeable_tasks(s)
    assert len(events(s, "pr_approved")) == 1 and not events(s, "merge_retry")
    assert task.merge_retry_at is None
