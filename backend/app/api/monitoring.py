from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep, get_or_404
from app.api.schemas import EmployeeStatus, NotificationOut, OrchestratorStatus, RunOut
from app.config import settings
from app.models import AgentRun, Employee, Event, Project, Wakeup
from app.orchestrator.dispatcher import orchestrator

router = APIRouter(tags=["monitoring"])


def _boss_events(project_id: int | None, unread_only: bool):
    q = select(Event).where(Event.target_role == "boss")
    if project_id is not None:
        q = q.where(Event.project_id == project_id)
    if unread_only:
        q = q.where(Event.processed_at.is_(None))
    return q


@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    s: SessionDep, project_id: int | None = None, unread_only: bool = True, limit: int = Query(100, ge=1, le=500)
):
    """What the team escalated to you, decisions to validate, mentions of @boss..."""
    events = await s.scalars(_boss_events(project_id, unread_only).order_by(Event.id.desc()).limit(limit))
    return [
        NotificationOut(
            id=e.id, project_id=e.project_id, type=e.type, payload=e.payload, created_at=e.created_at,
            read=e.processed_at is not None,
        )  # fmt: skip
        for e in events
    ]


@router.post("/notifications/{event_id}/read", status_code=204)
async def mark_read(event_id: int, s: SessionDep):
    event = await get_or_404(s, Event, event_id)
    event.processed_at = event.processed_at or datetime.now(UTC)
    await s.commit()


@router.post("/notifications/read-all", status_code=204)
async def mark_all_read(s: SessionDep, project_id: int | None = None):
    q = update(Event).where(Event.target_role == "boss", Event.processed_at.is_(None))
    if project_id is not None:
        q = q.where(Event.project_id == project_id)
    await s.execute(q.values(processed_at=datetime.now(UTC)))
    await s.commit()


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
    statuses = []
    for e in employees:
        out = EmployeeStatus(employee_id=e.id, name=e.name, title=e.title, status="resting")
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


@router.get("/orchestrator", response_model=OrchestratorStatus)
async def orchestrator_status(s: SessionDep):
    pending = await s.scalar(select(func.count()).select_from(Wakeup).where(Wakeup.started_at.is_(None)))
    return OrchestratorStatus(
        enabled=settings.orchestrator_enabled,
        running_employee_ids=orchestrator.running_employee_ids,
        pending_wakeups=pending,
    )
