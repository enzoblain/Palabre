from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import github, projects, services
from app.api.deps import SessionDep, get_or_404
from app.api.schemas import (
    DecisionOut,
    DecisionPatch,
    QuestionIn,
    QuestionOut,
    QuestionPatch,
    RoomIn,
    RoomOut,
    RoomPatch,
    TaskOut,
)
from app.models import Conversation, Decision, Employee, OpenQuestion, Project, RequestAnswer, Room, Task

router = APIRouter(tags=["rooms"])


async def load_room(s, room_id: int) -> Room:
    room = await s.scalar(select(Room).where(Room.id == room_id).options(selectinload(Room.members)))
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Room {room_id} not found")
    return room


def check_not_direction(room: Room) -> None:
    """The direction channel is fixed: the boss and the lead, for as long as the project lives."""
    if room.kind == services.DIRECTION:
        raise HTTPException(status.HTTP_409_CONFLICT, "The direction channel cannot be changed this way")


@router.get("/projects/{project_id}/rooms", response_model=list[RoomOut])
async def list_rooms(project_id: int, s: SessionDep):
    await get_or_404(s, Project, project_id)
    return list(
        await s.scalars(
            select(Room).where(Room.project_id == project_id).options(selectinload(Room.members)).order_by(Room.id)
        )
    )


@router.post("/projects/{project_id}/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(project_id: int, body: RoomIn, s: SessionDep):
    """A room (like a channel), with its first conversation. Members default to everyone."""
    await get_or_404(s, Project, project_id)
    q = select(Employee).where(Employee.project_id == project_id)
    if body.member_ids is not None:
        q = q.where(Employee.id.in_(body.member_ids))
    members = list(await s.scalars(q))
    if body.member_ids is not None and len(members) != len(set(body.member_ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Some members are not employees of this project")
    if body.name.strip().lower() == services.DIRECTION:
        raise HTTPException(status.HTTP_409_CONFLICT, "The direction channel is created with the project")
    room = Room(project_id=project_id, name=body.name, objective=body.objective, summary="", members=members)
    s.add(room)
    await s.flush()
    s.add(Conversation(room_id=room.id, title="General"))
    if body.objective:
        services.emit_event(s, project_id, "objective_set", {"room_id": room.id})
    await s.commit()
    return await load_room(s, room.id)


@router.get("/rooms/{room_id}", response_model=RoomOut)
async def get_room(room_id: int, s: SessionDep):
    return await load_room(s, room_id)


@router.patch("/rooms/{room_id}", response_model=RoomOut)
async def update_room(room_id: int, body: RoomPatch, s: SessionDep):
    """Changing the objective wakes up the positions that react to it."""
    room = await load_room(s, room_id)
    changes = body.model_dump(exclude_none=True)
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
    room = await get_or_404(s, Room, room_id)
    check_not_direction(room)
    await s.delete(room)
    await s.commit()


@router.put("/rooms/{room_id}/members/{employee_id}", response_model=RoomOut)
async def add_member(room_id: int, employee_id: int, s: SessionDep):
    room = await load_room(s, room_id)
    check_not_direction(room)
    employee = await get_or_404(s, Employee, employee_id)
    if employee.project_id != room.project_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This employee belongs to another project")
    if employee not in room.members:
        room.members.append(employee)
        await s.commit()
    return await load_room(s, room_id)


@router.delete("/rooms/{room_id}/members/{employee_id}", response_model=RoomOut)
async def remove_member(room_id: int, employee_id: int, s: SessionDep):
    room = await load_room(s, room_id)
    check_not_direction(room)
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


@router.patch("/decisions/{decision_id}", response_model=DecisionOut)
async def decide(decision_id: int, body: DecisionPatch, s: SessionDep):
    """Validate or reject a decision from the room document. A release is merged into
    production when validated (and stays proposed if GitHub refuses), closed when rejected.
    The request in direction about it, if any, is answered the same way."""
    decision = await get_or_404(s, Decision, decision_id)
    try:
        await projects.settle_decision(s, decision, RequestAnswer(body.status))
    except github.GitHubError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"GitHub refused the merge: {exc}") from None
    await s.commit()
    return decision


@router.post("/rooms/{room_id}/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
async def add_question(room_id: int, body: QuestionIn, s: SessionDep):
    await get_or_404(s, Room, room_id)
    question = OpenQuestion(room_id=room_id, question=body.question, asked_by=services.boss_display_name())
    s.add(question)
    await s.commit()
    return question


@router.patch("/questions/{question_id}", response_model=QuestionOut)
async def answer_question(question_id: int, body: QuestionPatch, s: SessionDep):
    question = await get_or_404(s, OpenQuestion, question_id)
    question.answer, question.resolved = body.answer, True
    await s.commit()
    return question
