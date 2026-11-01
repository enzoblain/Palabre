"""Turns events into wakeups: who must run, and in which context."""

from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.company.catalog import held_role_keys, load_catalog
from app.models import Conversation, Employee, Event, Room, Task, Wakeup, room_members
from app.orchestrator.event_types import TASK_EVENTS
from app.orchestrator.prompts import reason_for
from app.services import DIRECTION, DM

BATCH_SIZE = 200


def wakes_on(employee: Employee, event_type: str) -> bool:
    roles = load_catalog()["roles"]
    return any(event_type in roles[r].wakes_on for r in employee.roles)


async def _targets(s: AsyncSession, event: Event) -> list[Employee]:
    if event.target_employee_id is not None:
        employee = await s.get(Employee, event.target_employee_id)
        return [employee] if employee else []
    employees = await s.scalars(select(Employee).where(Employee.project_id == event.project_id))
    if event.target_role is not None:
        roles = load_catalog()["roles"]
        return [e for e in employees if event.target_role in held_role_keys(e.roles, roles)]
    # Broadcast: everyone whose position reacts to this event (catalog: wakes_on)
    return [e for e in employees if wakes_on(e, event.type)]


async def _conversation_id(s: AsyncSession, event: Event, task: Task | None) -> int | None:
    if conversation_id := event.payload.get("conversation_id"):
        return conversation_id
    if task is not None:
        return task.conversation_id
    room_q = select(Room.id).where(Room.project_id == event.project_id, Room.kind.notin_((DIRECTION, DM)))
    if room_id := event.payload.get("room_id"):
        room_q = room_q.where(Room.id == room_id)
    return await s.scalar(
        select(Conversation.id)
        .where(Conversation.room_id.in_(room_q))
        .order_by(Conversation.id.desc())
        .limit(1)
    )


async def _room_of(s: AsyncSession, conversation_id: int | None) -> tuple[int | None, set[int], bool]:
    """The conversation's room, the ids of its members, and whether it is closed to outsiders (direction or a DM)."""
    if conversation_id is None:
        return None, set(), False
    room_id = await s.scalar(select(Conversation.room_id).where(Conversation.id == conversation_id))
    members = await s.scalars(select(room_members.c.employee_id).where(room_members.c.room_id == room_id))
    kind = await s.scalar(select(Room.kind).where(Room.id == room_id))
    return room_id, set(members), kind in (DIRECTION, DM)


async def expand_events(s: AsyncSession) -> int:
    """Resolve pending events into wakeups. Events for the boss stay for the UI."""
    events = list(
        await s.scalars(
            select(Event)
            .where(
                Event.processed_at.is_(None),
                (Event.target_role.is_(None)) | (Event.target_role != "boss"),
            )
            .order_by(Event.id)
            .limit(BATCH_SIZE)
        )
    )
    for event in events:
        task = await s.get(Task, event.payload["task_id"]) if "task_id" in event.payload else None
        conversation_id = await _conversation_id(s, event, task)
        reason = reason_for(event.type, event.payload)
        room_id, members, is_closed = await _room_of(s, conversation_id)
        for employee in await _targets(s, event):
            is_task_run = event.type in TASK_EVENTS and task is not None and task.assignee_id == employee.id
            if not is_task_run and room_id is None:
                continue  # No conversation to talk in (or it was deleted)
            if not is_task_run and is_closed and employee.id not in members:
                continue  # Direction and DMs have fixed members; nobody is called in
            if not is_task_run and employee.id not in members:
                # Called into a room they are not in (a review, a mention...): they join it
                await s.execute(insert(room_members).values(room_id=room_id, employee_id=employee.id))
                members.add(employee.id)
            s.add(
                Wakeup(
                    employee_id=employee.id,
                    event_type=event.type,
                    kind="task" if is_task_run else "conversation",
                    conversation_id=None if is_task_run else conversation_id,
                    task_id=task.id if is_task_run else None,
                    reason=reason,
                )
            )
        event.processed_at = datetime.now(UTC)
    await s.commit()
    return len(events)
