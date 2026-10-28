from datetime import UTC, datetime

from fastapi import APIRouter, Query, status
from sqlalchemy import select, update

from app import services
from app.api.deps import SessionDep, get_or_404
from app.api.schemas import ConversationIn, ConversationOut, MessageIn, MessageOut
from app.models import Conversation, Employee, Event, Room

router = APIRouter(tags=["conversations"])


@router.get("/rooms/{room_id}/conversations", response_model=list[ConversationOut])
async def list_conversations(room_id: int, s: SessionDep):
    await get_or_404(s, Room, room_id)
    return list(await s.scalars(select(Conversation).where(Conversation.room_id == room_id).order_by(Conversation.id)))


@router.post("/rooms/{room_id}/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(room_id: int, body: ConversationIn, s: SessionDep):
    await get_or_404(s, Room, room_id)
    conversation = Conversation(room_id=room_id, title=body.title)
    s.add(conversation)
    await s.commit()
    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: int, s: SessionDep):
    return await get_or_404(s, Conversation, conversation_id)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: int,
    s: SessionDep,
    since_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Messages in chronological order; poll with since_id = last id seen."""
    await get_or_404(s, Conversation, conversation_id)
    return await services.get_messages(s, conversation_id, since_id, limit)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def post_message(conversation_id: int, body: MessageIn, s: SessionDep):
    """Post as the boss. @mentioned employees are woken up; without any mention,
    the lead is."""
    conversation = await get_or_404(s, Conversation, conversation_id)
    room = await get_or_404(s, Room, conversation.room_id)
    message = await services.post_message(s, room.project_id, conversation_id, body.content, None)
    mentioned = await s.scalar(
        select(Event.id).where(
            Event.type == "mention",
            Event.target_employee_id.in_(select(Employee.id).where(Employee.project_id == room.project_id)),
            Event.payload["message_id"].as_integer() == message.id,
        )
    )
    if mentioned is None:
        services.emit_event(
            s, room.project_id, "boss_message", {"conversation_id": conversation_id, "message_id": message.id}, role="lead"
        )
    # Posting lifts the throttle of this conversation (see Orchestrator._check_rate)
    await s.execute(
        update(Event)
        .where(
            Event.type == "conversation_throttled",
            Event.processed_at.is_(None),
            Event.payload["conversation_id"].as_integer() == conversation_id,
        )
        .values(processed_at=datetime.now(UTC))
    )
    await s.commit()
    return message
