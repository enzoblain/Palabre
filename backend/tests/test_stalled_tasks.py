"""A task run that ends without submitting is resumed a few times, orphans are caught, then the lead is told."""

from datetime import UTC, datetime, timedelta

from app.config import settings
from app.models import TaskStatus
from app.orchestrator import retries

from .conftest import make_task
from .test_dev_wakeups import Session, events


def stalled(**fields):
    return make_task(**({"status": TaskStatus.in_progress, "assignee_id": 7, "stalled_restarts": 0} | fields))


# scalar() answers, in order: dev busy? (dependencies are skipped without depends_on)
async def test_run_ended_without_submission_wakes_the_same_dev():
    task = stalled()
    assert await retries.restart_stalled_task(Session(), task)
    s = Session()
    await retries.restart_stalled_task(s, stalled())
    [wake] = events(s, "task_stalled")
    assert wake.target_employee_id == 7 and wake.payload["attempt"] == 1 and task.stalled_restarts == 1


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
