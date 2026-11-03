"""A task run that ends without submitting is resumed a few times, orphans are caught, then the lead is told."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import workflow
from app.config import settings
from app.models import AgentRun, TaskStatus
from app.orchestrator import dispatcher, retries

from .conftest import make_task
from .test_dev_wakeups import Session, events


def stalled(**fields):
    return make_task(**({"status": TaskStatus.in_progress, "assignee_id": 7, "stalled_restarts": 0} | fields))


async def test_run_ended_without_submission_wakes_the_same_dev():
    task, s = stalled(), Session()
    assert await retries.restart_stalled_task(s, task)
    [wake] = events(s, "task_stalled")
    assert wake.target_employee_id == 7 and wake.payload["attempt"] == 1 and task.stalled_restarts == 1


async def test_ended_run_hook_emits_task_stalled_for_an_unsubmitted_task():
    task = stalled()
    s = Session(get_result=task)
    await retries.on_task_run_ended(s, task.id)
    assert len(events(s, "task_stalled")) == 1 and s.commits == 1


def _finish_session(run, task):
    s = Session(get_result=task)
    s.get = _get_by_model(run, task)
    s.execute = _noop
    return s


def _get_by_model(run, task):
    async def get(model, _id, **_):
        return run if model is AgentRun else task

    return get


async def _noop(*_):
    return None


@pytest.mark.parametrize(("ok", "ended_calls", "failed_calls"), [(True, 1, 0), (False, 0, 1), (None, 0, 0)])
async def test_finish_routes_only_the_right_outcome_to_each_hook(monkeypatch, ok, ended_calls, failed_calls):
    ended, failed = [], []

    async def record_ended(_s, task_id):
        ended.append(task_id)

    async def record_failed(_s, task_id, _error):
        failed.append(task_id)

    monkeypatch.setattr(dispatcher, "on_task_run_ended", record_ended)
    monkeypatch.setattr(dispatcher, "on_task_run_failed", record_failed)
    run = SimpleNamespace(task_id=3, kind="task", finished_at=None, ok=None, error=None)
    orchestrator = dispatcher.Orchestrator.__new__(dispatcher.Orchestrator)
    await orchestrator._finish(_finish_session(run, stalled()), 1, [], ok=ok)
    assert (len(ended), len(failed)) == (ended_calls, failed_calls)


async def test_any_wakeup_by_someone_else_resets_the_count_but_a_nudge_does_not():
    task = stalled(stalled_restarts=2, unstarted_nudges=1)
    await workflow.wake_dev(Session(), task, "changes_requested")
    assert task.stalled_restarts == 0 and task.unstarted_nudges == 0

    task = stalled(stalled_restarts=2, unstarted_nudges=1)
    await workflow.wake_dev(Session(), task, "task_nudge", nudge=True)
    assert task.stalled_restarts == 2 and task.unstarted_nudges == 1


async def test_changes_requested_task_is_resumed_too():
    s = Session()
    assert await retries.restart_stalled_task(s, stalled(status=TaskStatus.changes_requested))
    assert events(s, "task_stalled")


async def test_submitted_task_is_left_alone():
    s = Session()
    assert not await retries.restart_stalled_task(s, stalled(status=TaskStatus.review))
    assert not s.added


async def test_busy_dev_is_not_woken_twice():
    s = Session(scalar=[123])
    task = stalled()
    assert not await retries.restart_stalled_task(s, task)
    assert not s.added and task.stalled_restarts == 0


async def test_lead_is_told_once_past_the_max_attempts():
    task = stalled(stalled_restarts=settings.max_stalled_restarts, conversation_id=1)
    s = Session()
    assert not await retries.restart_stalled_task(s, task)
    [alert] = events(s, "task_run_failed")
    assert alert.target_role == "lead" and not events(s, "task_stalled")

    s2 = Session()
    await retries.restart_stalled_task(s2, task)
    assert not s2.added


async def test_orphan_task_is_resumed_after_the_delay():
    old = datetime.now(UTC) - timedelta(minutes=settings.stalled_task_minutes + 1)
    task = stalled()
    # scalar(): last run end, open run, last wakeup, then dev busy
    s = Session(scalars=[[task]], scalar=[old, None, old])
    await retries.restart_orphan_tasks(s)
    assert len(events(s, "task_stalled")) == 1


async def test_orphan_with_a_recent_run_or_open_run_is_left_alone():
    recent = datetime.now(UTC)
    s = Session(scalars=[[stalled()]], scalar=[recent, None, None])
    await retries.restart_orphan_tasks(s)
    s2 = Session(scalars=[[stalled()]], scalar=[None, 5, None])
    await retries.restart_orphan_tasks(s2)
    assert not s.added and not s2.added


async def test_orphan_with_consecutive_failures_is_left_to_the_failure_retry():
    failed_run = SimpleNamespace(ok=False, finished_at=datetime.now(UTC))
    s = Session(scalars=[[stalled()], [failed_run]])
    await retries.restart_orphan_tasks(s)
    assert not s.added
