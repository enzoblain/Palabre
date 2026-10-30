"""Employee presence, derived from agent runs: working while a run is open, idle otherwise."""

from sqlalchemy import func, select

from app.models import AgentRun, Employee


def presence_query(project_id: int):
    """One query for the whole team: each employee, their open runs (if any) and their last run start."""
    last_run = (
        select(func.max(AgentRun.started_at))
        .where(AgentRun.employee_id == Employee.id)
        .correlate(Employee)
        .scalar_subquery()
    )
    return (
        select(
            Employee.id, Employee.name, Employee.roles,
            AgentRun.kind, AgentRun.task_id, AgentRun.conversation_id, AgentRun.started_at,
            last_run.label("last_run_at"),
        )  # fmt: skip
        .outerjoin(AgentRun, (AgentRun.employee_id == Employee.id) & AgentRun.finished_at.is_(None))
        .where(Employee.project_id == project_id)
        .order_by(Employee.id)
    )


async def team_presence(s, project_id: int) -> list[dict]:
    """One entry per employee; with several open runs, the most recent one is shown."""
    entries: dict[int, dict] = {}
    for row in (await s.execute(presence_query(project_id))).all():
        entry = entries.setdefault(
            row.id,
            dict(employee_id=row.id, name=row.name, roles=row.roles, state="idle", kind=None,
                 task_id=None, conversation_id=None, last_run_at=row.last_run_at, _since=None),
        )  # fmt: skip
        if row.kind is not None and (entry["_since"] is None or row.started_at > entry["_since"]):
            entry.update(state="working", kind=row.kind, task_id=row.task_id,
                         conversation_id=row.conversation_id, _since=row.started_at)  # fmt: skip
    return [{k: v for k, v in e.items() if k != "_since"} for e in entries.values()]
