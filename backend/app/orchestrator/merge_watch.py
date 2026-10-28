"""Tasks that became mergeable without a review (CI turned green) or that nobody merged:
the lead is woken up, then reminded once."""

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import workflow
from app.config import settings
from app.models import Project, Task, TaskStatus

# Seconds between two merge-rule checks of the same task (they ask GitHub about the CI)
CHECK_EVERY_S = 60
_last_check: dict[int, float] = {}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def watch_mergeable_tasks(s: AsyncSession) -> None:
    now = time.monotonic()
    tasks = await s.scalars(
        select(Task).where(Task.status == TaskStatus.review, Task.pr_number.is_not(None))
    )
    for task in list(tasks):
        reminder_due = (
            task.merge_ready_at is not None
            and task.merge_reminded_at is None
            and _aware(task.merge_ready_at) <= datetime.now(UTC) - timedelta(minutes=settings.merge_reminder_minutes)
        )
        if task.merge_ready_at is not None and not reminder_due:
            continue
        if task.merge_ready_at is None and now - _last_check.get(task.id, -CHECK_EVERY_S) < CHECK_EVERY_S:
            continue
        _last_check[task.id] = now
        project = await s.get(Project, task.project_id)
        if await workflow.merge_blockers(s, project, task):
            task.merge_ready_at = None  # A rule broke again (CI): announce it when fixed
            continue
        if reminder_due:
            await workflow.remind_merge(s, task)
        else:
            await workflow.mark_merge_ready(s, task, "the checks")
    await s.commit()
