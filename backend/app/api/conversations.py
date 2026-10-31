"""REST endpoints for conversations and their messages."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import github, projects, services
from app.api.deps import SessionDep, get_or_404
from app.api.schemas import ConversationIn, ConversationOut, MessageIn, MessageOut, RequestAnswerIn, UnreadSummaryItem
from app.models import Conversation, Employee, Event, Message, Project, RequestAnswer, Room, Wakeup
from app.orchestrator.dispatcher import orchestrator
from app.orchestrator.research import start_question

router = APIRouter(tags=["conversations"])


async def get_visible_room(s: AsyncSession, room_id: int) -> Room:
    """The room, or 404 when it is not one the boss sees (a team channel or a DM)."""
    room = await get_or_404(s, Room, room_id)
    if not await services.boss_sees(s, room):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Room {room_id} not found")
    return room


@router.get("/rooms/{room_id}/conversations", response_model=list[ConversationOut])
async def list_conversations(room_id: int, s: SessionDep):
    await get_visible_room(s, room_id)
    return list(await s.scalars(select(Conversation).where(Conversation.room_id == room_id).order_by(Conversation.id)))


@router.get("/projects/{project_id}/unread-summary", response_model=list[UnreadSummaryItem])
async def unread_summary(project_id: int, s: SessionDep):
    """One cheap poll for the whole project: per visible conversation, its latest message ids."""
    await get_or_404(s, Project, project_id)
    q = (
        select(
            Conversation.id,
            func.coalesce(func.max(Message.id), 0),
            func.coalesce(func.max(Message.id).filter(Message.employee_id.is_not(None)), 0),
        )
        .join(Room, Room.id == Conversation.room_id)
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Room.project_id == project_id)
        .group_by(Conversation.id)
        .order_by(Conversation.id)
    )
    rows = await s.execute(services.boss_rooms(q))
    return [UnreadSummaryItem(conversation_id=c, last_id=last, last_employee_message_id=emp) for c, last, emp in rows]


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
    only the lead is woken up. A research group starts researching the question instead."""
    conversation = await get_or_404(s, Conversation, conversation_id)
    room = await get_visible_room(s, conversation.room_id)
    project = await get_or_404(s, Project, room.project_id)
    if project.kind == "company" and room.kind != services.DIRECTION:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The boss only writes in the direction channel; the other channels are read-only",
        )
    message = await services.post_message(s, room.project_id, conversation_id, body.content, None)
    mentioned = await s.scalar(
        select(Event.id).where(
            Event.type == "mention",
            Event.target_employee_id.in_(select(Employee.id).where(Employee.project_id == room.project_id)),
            Event.payload["message_id"].as_integer() == message.id,
        )
    )
    if mentioned is None:
        if project.kind == "research":
            # A new question for the group: it goes through the research phases again
            start_question(s, project, conversation_id, message.id)
        else:
            services.emit_event(
                s, room.project_id, "boss_message", {"conversation_id": conversation_id, "message_id": message.id},
                role="lead",
            )  # fmt: skip
    # Posting lifts the throttle of this conversation (see Orchestrator._check_rate)
    await _clear_throttle(s, conversation_id)
    await s.commit()
    return message


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


@router.post("/messages/{message_id}/answer", response_model=MessageOut)
async def answer_request(message_id: int, body: RequestAnswerIn, s: SessionDep):
    """The boss answers a request of the lead: validate, reject or nuance (with a comment).
    Only once. Validating a release merges its pull request. The lead is woken up with the answer."""
    await get_or_404(s, Message, message_id)
    try:
        return await projects.answer_request(s, message_id, RequestAnswer(body.answer), body.comment)
    except github.GitHubError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"GitHub refused the merge: {exc}") from None
