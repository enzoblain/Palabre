"""REST endpoints for conversations and their messages."""

from datetime import UTC, datetime

from fastapi import APIRouter, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import services
from app.api.deps import SessionDep, get_or_404
from app.api.errors import ApiError, ErrorCode
from app.api.schemas import ConversationIn, ConversationOut, MessageIn, MessageOut
from app.models import Conversation, Employee, Event, Message, Room, Wakeup
from app.orchestrator.dispatcher import orchestrator

router = APIRouter(tags=["conversations"])


async def get_visible_room(s: AsyncSession, room_id: int) -> Room:
    """The room, or 404 when it is not one the boss sees (a team channel or a DM)."""
    room = await get_or_404(s, Room, room_id)
    if not services.boss_sees(room):
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.ROOM_NOT_FOUND, f"Room {room_id} not found")
    return room


@router.get("/rooms/{room_id}/conversations", response_model=list[ConversationOut])
async def list_conversations(room_id: int, s: SessionDep):
    await get_visible_room(s, room_id)
    return list(await s.scalars(select(Conversation).where(Conversation.room_id == room_id).order_by(Conversation.id)))


@router.post("/rooms/{room_id}/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(room_id: int, body: ConversationIn, s: SessionDep):
    await get_visible_room(s, room_id)
    conversation = Conversation(room_id=room_id, title=body.title)
    s.add(conversation)
    await s.commit()
    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: int, s: SessionDep):
    conversation = await get_or_404(s, Conversation, conversation_id)
    await get_visible_room(s, conversation.room_id)
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: int,
    s: SessionDep,
    since_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Messages in chronological order; poll with since_id = last id seen."""
    conversation = await get_or_404(s, Conversation, conversation_id)
    await get_visible_room(s, conversation.room_id)
    return await services.get_messages(s, conversation_id, since_id, limit)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def post_message(conversation_id: int, body: MessageIn, s: SessionDep):
    """Post as the boss. In a company the boss only writes in the direction channel, and
    only the lead is woken up."""
    conversation = await get_or_404(s, Conversation, conversation_id)
    room = await get_visible_room(s, conversation.room_id)
    if room.kind != services.DIRECTION:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.BOSS_READ_ONLY_ROOM,
            "The boss only writes in the direction channel; the other channels are read-only",
        )
    message = await services.post_message(s, room.project_id, conversation_id, body.content, None)
    answered = await services.answer_pending_requests(s, room.project_id, message)
    mentioned = await s.scalar(
        select(Event.id).where(
            Event.type == "mention",
            Event.target_employee_id.in_(select(Employee.id).where(Employee.project_id == room.project_id)),
            Event.payload["message_id"].as_integer() == message.id,
        )
    )
    if mentioned is None or answered:  # a mention does not tell the lead which requests were answered
        _wake_lead(s, room.project_id, conversation_id, message, answered)
    # Posting lifts the throttle of this conversation (see Orchestrator._check_rate)
    await _clear_throttle(s, conversation_id)
    await s.commit()
    return message


def _wake_lead(s: AsyncSession, project_id: int, conversation_id: int, message: Message, answered: list[Message]) -> None:
    """The boss wrote to the lead. Their message answered the pending requests (already closed): the lead
    is woken up with them, to interpret the reply."""
    payload = {"conversation_id": conversation_id, "message_id": message.id}
    if answered:
        payload["requests"] = services.describe_answered_requests(answered)
    services.emit_event(s, project_id, "ceo_answer" if answered else "boss_message", payload, role="lead")


async def _clear_throttle(s: AsyncSession, conversation_id: int) -> None:
    """Marks the pending "conversation_throttled" notices of a conversation as handled."""
    await s.execute(
        update(Event)
        .where(
            Event.type == "conversation_throttled",
            Event.processed_at.is_(None),
            Event.payload["conversation_id"].as_integer() == conversation_id,
        )
        .values(processed_at=datetime.now(UTC))
    )
    # Wakeups held back by the throttle can run now
    await s.execute(
        update(Wakeup)
        .where(Wakeup.conversation_id == conversation_id, Wakeup.started_at.is_(None), Wakeup.not_before.is_not(None))
        .values(not_before=None)
    )


@router.post("/conversations/{conversation_id}/lift-rate-limit", status_code=status.HTTP_204_NO_CONTENT)
async def lift_rate_limit(conversation_id: int, s: SessionDep):
    """Restarts the anti-loop window of a conversation (admin token): agents can be woken in it again."""
    conversation = await get_or_404(s, Conversation, conversation_id)
    room = await get_visible_room(s, conversation.room_id)
    await orchestrator.lift_rate_limit(s, room.project_id, conversation_id)
    await _clear_throttle(s, conversation_id)
    await s.commit()
