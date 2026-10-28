"""Tasks that became mergeable without a review (CI turned green) or that nobody merged:
the lead is woken up, then reminded once."""

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import github, workflow
from app.config import settings
from app.models import Project, Task, TaskStatus

# Seconds between two merge-rule checks of the same task (they ask GitHub about the CI)
CHECK_EVERY_S = 60
_last_check: dict[int, float] = {}

log = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def watch_mergeable_tasks(s: AsyncSession) -> None:
    now = time.monotonic()
    tasks = await s.scalars(
        select(Task).where(Task.status == TaskStatus.review, Task.pr_number.is_not(None))
    )
    tasks = list(tasks)
    for gone in _last_check.keys() - {t.id for t in tasks}:
        del _last_check[gone]
    for task in tasks:
        reminder_due = (
            task.merge_ready_at is not None
            and task.lead_reminded_at is None
            and _aware(task.merge_ready_at) <= datetime.now(UTC) - timedelta(minutes=settings.merge_reminder_minutes)
        )
        if task.merge_ready_at is not None and not reminder_due:
            continue
        if task.merge_ready_at is None and now - _last_check.get(task.id, -CHECK_EVERY_S) < CHECK_EVERY_S:
            continue
        _last_check[task.id] = now
        project = await s.get(Project, task.project_id)
        try:
            blockers = await workflow.merge_blockers(s, project, task)
        except github.GitHubError as exc:
            log.warning("Task #%s: merge rules could not be checked: %s", task.id, exc)
            continue  # One broken task must not stop the others
        if blockers:
            task.merge_ready_at = None  # A rule broke again (CI): announce it when fixed
            continue
        if reminder_due:
            await workflow.remind_merge(s, task)
        else:
            await workflow.mark_merge_ready(s, task, "the checks")
    await s.commit()
