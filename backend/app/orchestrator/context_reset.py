"""Fresh start of an employee's context every N finished tasks.

The context is what `--resume` brings back: the Claude sessions in `agent_sessions`. The prompts
rebuild everything else from the database on each run, and notes, tasks, room documents and chat
live in their own tables, so none of that is touched.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AgentSession, Employee, Task, TaskStatus

log = logging.getLogger(__name__)


async def finished_tasks_since_reset(s: AsyncSession, employee: Employee) -> int:
    """Tasks of the employee merged or cancelled since their last reset (or their arrival)."""
    since = employee.context_reset_at or employee.created_at
    query = select(func.count()).select_from(Task).where(
        Task.assignee_id == employee.id, Task.status.in_([TaskStatus.done, TaskStatus.cancelled])
    )
    if since is not None:
        query = query.where(Task.updated_at >= since)
    return await s.scalar(query) or 0


async def reset_context_if_due(s: AsyncSession, employee: Employee) -> bool:
    """Forget the employee's Claude sessions once they reached the threshold; the counter restarts.
    Called while preparing a run, so a run in progress is never cut."""
    every = settings.context_reset_every_tasks
    if every <= 0 or await finished_tasks_since_reset(s, employee) < every:
        return False
    await s.execute(delete(AgentSession).where(AgentSession.employee_id == employee.id))
    employee.context_reset_at = datetime.now(UTC)
    await s.commit()
    log.info("%s: %s tasks finished, starting on a blank context", employee.name, every)
    return True
