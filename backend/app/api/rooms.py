"""REST endpoints for rooms and their shared document."""

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import services
from app.api.conversations import get_visible_room
from app.api.deps import SessionDep, get_or_404
from app.api.errors import ApiError, ErrorCode
from app.api.schemas import (
    DecisionOut,
    QuestionIn,
    QuestionOut,
    QuestionPatch,
    RoomOut,
    RoomPatch,
    TaskOut,
)
from app.models import Decision, Employee, OpenQuestion, Project, Room, Task

router = APIRouter(tags=["rooms"])


async def load_room(s, room_id: int) -> Room:
    room = await s.scalar(select(Room).where(Room.id == room_id).options(selectinload(Room.members)))
    if room is None or not services.boss_sees(room):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.ROOM_NOT_FOUND, f"Room {room_id} not found")
    return room


def check_not_direction(room: Room) -> None:
    """The direction channel is fixed: the boss and the lead, for as long as the project lives."""
    if room.kind == services.DIRECTION:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            ErrorCode.DIRECTION_ROOM_IMMUTABLE,
            "The direction channel cannot be changed this way",
        )


def check_not_dm(room: Room) -> None:
    """A DM is exactly its two employees, named after them: no admin edit, no deletion."""
    if room.kind == services.DM:
        raise ApiError(
            status.HTTP_409_CONFLICT, ErrorCode.DM_IMMUTABLE, "A direct message cannot be changed this way"
        )


@router.get("/projects/{project_id}/rooms", response_model=list[RoomOut])
async def list_rooms(project_id: int, s: SessionDep):
    await get_or_404(s, Project, project_id)
    q = select(Room).where(Room.project_id == project_id).options(selectinload(Room.members)).order_by(Room.id)
    return list(await s.scalars(services.boss_rooms(q)))


@router.get("/rooms/{room_id}", response_model=RoomOut)
async def get_room(room_id: int, s: SessionDep):
    return await load_room(s, room_id)


@router.patch("/rooms/{room_id}", response_model=RoomOut)
async def update_room(room_id: int, body: RoomPatch, s: SessionDep):
    """Changing the objective wakes up the positions that react to it."""
    room = await load_room(s, room_id)
    changes = body.model_dump(exclude_none=True)
    check_not_dm(room)
    if "name" in changes:
        check_not_direction(room)
    for field, value in changes.items():
        setattr(room, field, value)
    if "objective" in changes:
        services.emit_event(s, room.project_id, "objective_set", {"room_id": room.id})
    await s.commit()
    return await load_room(s, room_id)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(room_id: int, s: SessionDep):
    room = await load_room(s, room_id)
    check_not_direction(room)
    check_not_dm(room)  # DMs last forever: nothing deletes or expires them
    await s.delete(room)
    await s.commit()


@router.put("/rooms/{room_id}/members/{employee_id}", response_model=RoomOut)
async def add_member(room_id: int, employee_id: int, s: SessionDep):
    room = await load_room(s, room_id)
    check_not_direction(room)
    check_not_dm(room)
    employee = await get_or_404(s, Employee, employee_id)
    if employee.project_id != room.project_id:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.EMPLOYEE_OTHER_PROJECT,
            "This employee belongs to another project",
        )
    if employee not in room.members:
        room.members.append(employee)
        await s.commit()
    return await load_room(s, room_id)


@router.delete("/rooms/{room_id}/members/{employee_id}", response_model=RoomOut)
async def remove_member(room_id: int, employee_id: int, s: SessionDep):
    room = await load_room(s, room_id)
    check_not_direction(room)
    check_not_dm(room)
    room.members = [m for m in room.members if m.id != employee_id]
    await s.commit()
    return await load_room(s, room_id)


# --- Room document -----------------------------------------------------------------


@router.get("/rooms/{room_id}/document")
async def get_document(room_id: int, s: SessionDep) -> dict:
    """The shared document: objective, summary, decisions, questions, who does what."""
    room = await load_room(s, room_id)
    decisions = await s.scalars(select(Decision).where(Decision.room_id == room_id).order_by(Decision.id))
    questions = await s.scalars(select(OpenQuestion).where(OpenQuestion.room_id == room_id).order_by(OpenQuestion.id))
    tasks = await s.scalars(
        select(Task).where(Task.room_id == room_id).options(selectinload(Task.assignee)).order_by(Task.id)
    )
    return {
        "room": RoomOut.model_validate(room),
        "decisions": [DecisionOut.model_validate(d) for d in decisions],
        "questions": [QuestionOut.model_validate(q) for q in questions],
        "tasks": [TaskOut.model_validate(t) for t in tasks],
    }


@router.post("/rooms/{room_id}/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
async def add_question(room_id: int, body: QuestionIn, s: SessionDep):
    await get_visible_room(s, room_id)
    question = OpenQuestion(room_id=room_id, question=body.question, asked_by=services.boss_display_name())
    s.add(question)
    await s.commit()
    return question


@router.patch("/questions/{question_id}", response_model=QuestionOut)
async def answer_question(question_id: int, body: QuestionPatch, s: SessionDep):
    question = await get_or_404(s, OpenQuestion, question_id)
    await load_room(s, question.room_id)
    question.answer, question.resolved = body.answer, True
    await s.commit()
    return question
