"""Task runs that failed (git error, crash, timeout...) are retried a few times, then
the lead is told."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, Task, TaskStatus, Wakeup
from app.services import emit_event

RUNNABLE_TASK_STATUSES = {TaskStatus.todo, TaskStatus.in_progress, TaskStatus.changes_requested}
MAX_TASK_ATTEMPTS = 3
RETRY_DELAY = timedelta(minutes=5)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def consecutive_failures(s: AsyncSession, task_id: int) -> tuple[int, datetime | None]:
    """Failed task runs since the last successful one, and when the latest ended.
    Skipped runs (ok is None) do not count."""
    runs = await s.scalars(
        select(AgentRun)
        .where(AgentRun.task_id == task_id, AgentRun.kind == "task", AgentRun.ok.is_not(None))
        .order_by(AgentRun.id.desc())
        .limit(MAX_TASK_ATTEMPTS)
    )
    count, last = 0, None
    for run in runs:
        if run.ok:
            break
        count += 1
        last = last or run.finished_at
    return count, last


async def retry_failed_tasks(s: AsyncSession) -> None:
    now = datetime.now(UTC)
    tasks = await s.scalars(
        select(Task).where(Task.status.in_(RUNNABLE_TASK_STATUSES), Task.assignee_id.is_not(None))
    )
    for task in list(tasks):
        failures, last = await consecutive_failures(s, task.id)
        if not failures or failures >= MAX_TASK_ATTEMPTS or last is None or _aware(last) > now - RETRY_DELAY:
            continue
        pending = await s.scalar(
            select(Wakeup.id).where(Wakeup.task_id == task.id, Wakeup.finished_at.is_(None)).limit(1)
        )
        if pending is not None:
            continue
        if task.depends_on:
            statuses = await s.scalars(select(Task.status).where(Task.id.in_(task.depends_on)))
            if any(st != TaskStatus.done for st in statuses):
                continue
        emit_event(
            s, task.project_id, "task_retry", {"task_id": task.id, "attempt": failures + 1},
            employee_id=task.assignee_id,
        )  # fmt: skip
    await s.commit()


async def on_task_run_failed(s: AsyncSession, task_id: int, error: str | None) -> None:
    """After the last attempt, the lead is woken up to sort it out (or ask the boss)."""
    failures, _ = await consecutive_failures(s, task_id)
    task = await s.get(Task, task_id)
    if task is None or failures != MAX_TASK_ATTEMPTS:
        return
    payload = {
        "task_id": task.id, "conversation_id": task.conversation_id, "attempts": failures,
        "error": (error or "unknown error")[:300],
    }  # fmt: skip
    emit_event(s, task.project_id, "task_run_failed", payload, role="lead")
    await s.commit()
