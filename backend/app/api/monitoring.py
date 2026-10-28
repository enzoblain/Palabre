from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.accounts import assign_accounts
from app.api.deps import SessionDep, get_or_404
from app.api.schemas import EmployeeStatus, OrchestratorStatus, RunOut
from app.config import settings
from app.models import AgentRun, Employee, Project, Wakeup
from app.orchestrator.dispatcher import orchestrator

router = APIRouter(tags=["monitoring"])


@router.get("/projects/{project_id}/runs", response_model=list[RunOut])
async def list_runs(project_id: int, s: SessionDep, limit: int = Query(50, ge=1, le=500)):
    """Latest agent runs (most recent first), with errors and cost."""
    await get_or_404(s, Project, project_id)
    return list(
        await s.scalars(
            select(AgentRun)
            .join(Employee, Employee.id == AgentRun.employee_id)
            .where(Employee.project_id == project_id)
            .options(selectinload(AgentRun.employee))
            .order_by(AgentRun.id.desc())
            .limit(limit)
        )
    )


@router.get("/projects/{project_id}/team-status", response_model=list[EmployeeStatus])
async def team_status(project_id: int, s: SessionDep):
    """Who is working right now, who is about to, and who is resting."""
    await get_or_404(s, Project, project_id)
    employees = list(await s.scalars(select(Employee).where(Employee.project_id == project_id).order_by(Employee.id)))
    ids = [e.id for e in employees]
    running = set(orchestrator.running_employee_ids)
    waiting = set(
        await s.scalars(select(Wakeup.employee_id).where(Wakeup.employee_id.in_(ids), Wakeup.started_at.is_(None)))
    )
    open_runs = {
        run.employee_id: run
        for run in await s.scalars(
            select(AgentRun).where(AgentRun.employee_id.in_(ids), AgentRun.finished_at.is_(None)).order_by(AgentRun.id)
        )
    }
    accounts = assign_accounts(employees)
    statuses = []
    for e in employees:
        out = EmployeeStatus(employee_id=e.id, name=e.name, title=e.title, status="resting", account=accounts[e.id])
        if not settings.orchestrator_enabled:
            out.status = "offline"
        elif e.id in running:
            out.status = "working"
            if run := open_runs.get(e.id):
                out.kind, out.conversation_id, out.task_id, out.since = (
                    run.kind, run.conversation_id, run.task_id, run.started_at
                )
        elif e.id in waiting:
            out.status = "waiting"
        statuses.append(out)
    return statuses


@router.get("/projects/{project_id}/research-phase")
async def research_phase(project_id: int, s: SessionDep) -> dict:
    """Where the current research question stands (null for a company)."""
    project = await get_or_404(s, Project, project_id)
    return {"phase": project.research_phase}


@router.get("/orchestrator", response_model=OrchestratorStatus)
async def orchestrator_status(s: SessionDep):
    pending = await s.scalar(select(func.count()).select_from(Wakeup).where(Wakeup.started_at.is_(None)))
    return OrchestratorStatus(
        enabled=settings.orchestrator_enabled,
        running_employee_ids=orchestrator.running_employee_ids,
        pending_wakeups=pending,
    )
