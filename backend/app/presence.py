"""Employee presence, derived from agent runs: working while a run is open, idle otherwise."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import settings
from app.models import AgentRun, Employee


def presence_query(project_id: int):
    """One query for the whole team: each employee, their open runs (if any) and their last run start."""
    last_run = (
        select(func.max(AgentRun.started_at))
        .where(AgentRun.employee_id == Employee.id)
        .correlate(Employee)
        .scalar_subquery()
    )
    # A run open for longer than the run timeout is an orphan, not work in progress
    oldest = datetime.now(UTC) - timedelta(seconds=settings.agent_timeout_s)
    return (
        select(
            Employee.id, Employee.name, Employee.roles,
            AgentRun.kind, AgentRun.task_id, AgentRun.conversation_id, AgentRun.started_at,
            last_run.label("last_run_at"),
        )  # fmt: skip
        .outerjoin(AgentRun, (AgentRun.employee_id == Employee.id) & AgentRun.finished_at.is_(None) & (AgentRun.started_at > oldest))
        .where(Employee.project_id == project_id)
        .order_by(Employee.id, AgentRun.started_at)
    )


async def team_presence(s, project_id: int) -> list[dict]:
    """One entry per employee; rows come ordered by start, so with several open runs the latest wins."""
    entries: dict[int, dict] = {}
    for row in (await s.execute(presence_query(project_id))).all():
        entry = entries.setdefault(
            row.id,
            dict(employee_id=row.id, name=row.name, roles=row.roles, state="idle", kind=None,
                 task_id=None, conversation_id=None, last_run_at=row.last_run_at),
        )  # fmt: skip
        if row.kind is not None:
            entry.update(state="working", kind=row.kind, task_id=row.task_id,
                         conversation_id=row.conversation_id)  # fmt: skip
    return list(entries.values())
