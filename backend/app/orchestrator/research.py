"""The phases of a research question: research → debate → conclusion → report → done.

The boss's question starts phase 1. Each next phase starts once the group has gone
quiet: nobody running or about to run, and no activity for SETTLE.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, Conversation, Employee, Event, Project, Room, Wakeup
from app.services import emit_event

PHASES = ["research", "debate", "conclusion", "report", "done"]
SETTLE = timedelta(seconds=20)
# Event that starts each phase: everyone, except the report (the rapporteur)
NEXT_EVENT = {"research": "research_debate", "debate": "research_conclude", "conclusion": "research_report"}


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def start_question(s: AsyncSession, project: Project, conversation_id: int, message_id: int) -> None:
    """The boss asked something: every peer researches it (phase 1). Caller commits."""
    project.research_phase = "research"
    emit_event(s, project.id, "research_start", {"conversation_id": conversation_id, "message_id": message_id})


async def advance_research(s: AsyncSession) -> None:
    projects = await s.scalars(
        select(Project).where(Project.kind == "research", Project.research_phase.in_(list(NEXT_EVENT) + ["report"]))
    )
    for project in list(projects):
        if not await _quiet(s, project):
            continue
        if project.research_phase == "report":
            project.research_phase = "done"
            continue
        conversation_id = await s.scalar(
            select(Conversation.id)
            .join(Room, Room.id == Conversation.room_id)
            .where(Room.project_id == project.id)
            .order_by(Room.id, Conversation.id)
            .limit(1)
        )
        event = NEXT_EVENT[project.research_phase]
        emit_event(
            s, project.id, event, {"conversation_id": conversation_id},
            role="rapporteur" if event == "research_report" else None,
        )  # fmt: skip
        project.research_phase = PHASES[PHASES.index(project.research_phase) + 1]
    await s.commit()


async def _quiet(s: AsyncSession, project: Project) -> bool:
    """Nobody of the group is running or about to, and nothing happened for SETTLE."""
    employees = select(Employee.id).where(Employee.project_id == project.id)
    pending_event = await s.scalar(
        select(Event.id)
        .where(
            Event.project_id == project.id,
            Event.processed_at.is_(None),
            (Event.target_role.is_(None)) | (Event.target_role != "boss"),
        )
        .limit(1)
    )
    open_wakeup = await s.scalar(
        select(Wakeup.id).where(Wakeup.employee_id.in_(employees), Wakeup.finished_at.is_(None)).limit(1)
    )
    if pending_event is not None or open_wakeup is not None:
        return False
    last = _aware(
        await s.scalar(select(func.max(AgentRun.finished_at)).where(AgentRun.employee_id.in_(employees)))
    )
    return last is None or datetime.now(UTC) - last >= SETTLE
