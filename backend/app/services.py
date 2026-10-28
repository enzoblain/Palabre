"""Conversation, room document, notes and events. Shared by the MCP server and the API."""

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AppSetting,
    Conversation,
    Decision,
    DecisionStatus,
    Employee,
    Event,
    Message,
    Note,
    OpenQuestion,
    Room,
    Task,
    TaskStatus,
)

MENTION_RE = re.compile(r"@([\w-]+)")

# What a chat message from an agent may look like (the boss is free). Links count by
# their text, code blocks not at all: sources and snippets are welcome.
CHAT_MAX_CHARS = {"company": 450, "research": 700}
CHAT_MAX_LIST_ITEMS = 4
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.S)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)|https?://\S+")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.M)
BOSS_ALIASES = {"boss", "ceo"}
DIRECTION = "direction"


class WorkflowError(Exception):
    """A rule of the company was not respected; the message is shown to the agent."""


# Languages the team can work in: key (stored) → name in that language (shown in the UI)
LANGUAGES = {
    "French": "Français",
    "English": "English",
    "Spanish": "Español",
    "German": "Deutsch",
    "Italian": "Italiano",
    "Portuguese": "Português",
    "Dutch": "Nederlands",
}
DEFAULT_SETTINGS = {"boss_name": "", "language": "French"}

# Loaded from the database at startup, changed from the UI's settings page
_app_settings = dict(DEFAULT_SETTINGS)


async def load_app_settings(s: AsyncSession) -> None:
    for row in await s.scalars(select(AppSetting).where(AppSetting.key.in_(DEFAULT_SETTINGS))):
        _app_settings[row.key] = row.value


async def set_app_setting(s: AsyncSession, key: str, value: str) -> None:
    row = await s.get(AppSetting, key)
    if row is None:
        s.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    await s.commit()
    _app_settings[key] = value


def boss_name() -> str:
    """The name the user gave in the settings (empty until they do)."""
    return _app_settings["boss_name"]


def boss_display_name() -> str:
    return boss_name() or "Boss"


def team_language() -> str:
    """The language the employees speak and write in."""
    return _app_settings["language"]


def check_chat_message(content: str, kind: str) -> None:
    """Refuse what nobody writes in a team chat, and say how to fix it."""
    text = _LINK_RE.sub(lambda m: m.group(1) or "link", _CODE_BLOCK_RE.sub("", content)).strip()
    problems = []
    if "**" in text or "__" in text:
        problems.append("no bold")
    if re.search(r"^\s*#{1,6}\s", text, re.M):
        problems.append("no headings")
    if len(_LIST_ITEM_RE.findall(text)) > CHAT_MAX_LIST_ITEMS:
        problems.append(f"no list of more than {CHAT_MAX_LIST_ITEMS} items")
    limit = CHAT_MAX_CHARS.get(kind, CHAT_MAX_CHARS["company"])
    if len(text) > limit:
        problems.append(f"at most {limit} characters (this one has {len(text)})")
    if problems:
        raise WorkflowError(
            "Not sent: this reads like a report, not a chat message (" + "; ".join(problems) + "). "
            "Say it the way you would to a colleague, in a sentence or two. Split it into several short "
            "messages if you have several things to say, and put long content (plans, specs, evidence) "
            "in a task, a decision or the room document."
        )


def emit_event(
    s: AsyncSession,
    project_id: int,
    type: str,
    payload: dict | None = None,
    *,
    employee_id: int | None = None,
    role: str | None = None,
) -> None:
    s.add(
        Event(
            project_id=project_id,
            type=type,
            payload=payload or {},
            target_employee_id=employee_id,
            target_role=role,
        )
    )


# --- Messages ----------------------------------------------------------------------


async def get_messages(
    s: AsyncSession, conversation_id: int, since_id: int | None = None, limit: int = 50
) -> list[Message]:
    q = select(Message).where(Message.conversation_id == conversation_id)
    if since_id is not None:
        q = q.where(Message.id > since_id).order_by(Message.id).limit(limit)
        return list(await s.scalars(q))
    # Without a cursor: the last `limit` messages, in chronological order
    q = q.order_by(Message.id.desc()).limit(limit)
    return list(reversed(list(await s.scalars(q))))


async def last_message_id(s: AsyncSession, conversation_id: int) -> int:
    return await s.scalar(
        select(func.coalesce(func.max(Message.id), 0)).where(Message.conversation_id == conversation_id)
    )


async def post_message(
    s: AsyncSession, project_id: int, conversation_id: int, content: str, author: Employee | None
) -> Message:
    """Post a message (author None = the boss) and wake up everyone @mentioned."""
    msg = Message(
        conversation_id=conversation_id,
        employee_id=author.id if author else None,
        author_name=author.name if author else boss_display_name(),
        content=content,
    )
    s.add(msg)
    await s.flush()

    mentioned = {m.lower() for m in MENTION_RE.findall(content)}
    if mentioned:
        payload = {"conversation_id": conversation_id, "message_id": msg.id}
        boss_names = BOSS_ALIASES | ({boss_name().lower()} if boss_name() else set())
        if mentioned & boss_names:
            emit_event(s, project_id, "mention", payload, role="boss")
        employees = await s.scalars(select(Employee).where(Employee.project_id == project_id))
        in_direction = await s.scalar(
            select(Room.id)
            .join(Conversation, Conversation.room_id == Room.id)
            .where(Conversation.id == conversation_id, Room.kind == DIRECTION)
        )
        for employee in employees:
            if in_direction and "lead" not in employee.roles:
                continue  # Direction is between the boss and the lead
            if employee.name.lower() in mentioned and (author is None or employee.id != author.id):
                emit_event(s, project_id, "mention", payload, employee_id=employee.id)

    await s.commit()
    await s.refresh(msg)
    return msg


# --- Channels ----------------------------------------------------------------------


async def create_channel(s: AsyncSession, project_id: int, name: str, member_names: list[str]) -> Room:
    """A team channel (a room with a first conversation). The lead is always in it."""
    name = name.strip().lstrip("#").strip()
    if not name:
        raise WorkflowError("A channel needs a name")
    rooms = await s.scalars(select(Room).where(Room.project_id == project_id))
    if any(r.name.lower() == name.lower() for r in rooms):
        raise WorkflowError(f"A channel named {name} already exists")
    employees = list(await s.scalars(select(Employee).where(Employee.project_id == project_id)))
    wanted = {n.lstrip("@").lower() for n in member_names}
    unknown = wanted - {e.name.lower() for e in employees}
    if unknown:
        raise WorkflowError(f"Unknown employees: {', '.join(sorted(unknown))}")
    members = [e for e in employees if e.name.lower() in wanted or "lead" in e.roles]
    room = Room(project_id=project_id, name=name, members=members)
    s.add(room)
    await s.flush()
    s.add(Conversation(room_id=room.id, title="General"))
    await s.commit()
    return room


async def team_context(s: AsyncSession, project_id: int, room_id: int, conversation_id: int) -> tuple[int, int]:
    """Where a task lives. Called from direction, it goes to the first team channel: the
    people it concerns (reviewers, QA...) are not in direction and cannot be woken there."""
    if await s.scalar(select(Room.kind).where(Room.id == room_id)) != DIRECTION:
        return room_id, conversation_id
    team_room_id = await s.scalar(
        select(Room.id).where(Room.project_id == project_id, Room.kind != DIRECTION).order_by(Room.id).limit(1)
    )
    if team_room_id is None:
        raise WorkflowError("There is no team channel to put the task in")
    team_conversation_id = await s.scalar(
        select(Conversation.id).where(Conversation.room_id == team_room_id).order_by(Conversation.id.desc()).limit(1)
    )
    return team_room_id, team_conversation_id


async def channel_conversation_id(s: AsyncSession, project_id: int, name: str) -> int:
    """The conversation to post in for the channel `name`."""
    wanted = name.strip().lstrip("#").lower()
    # Direction is found by its kind: a rename must not break the relay
    named = Room.kind == DIRECTION if wanted == DIRECTION else func.lower(Room.name) == wanted
    conversation_id = await s.scalar(
        select(Conversation.id)
        .join(Room, Room.id == Conversation.room_id)
        .where(Room.project_id == project_id, named)
        .order_by(Conversation.id.desc())  # the active one is the latest
        .limit(1)
    )
    if conversation_id is None:
        raise WorkflowError(f"No channel named {name}")
    return conversation_id


# --- Room document -----------------------------------------------------------------


async def room_context(s: AsyncSession, room_id: int) -> dict:
    room = await s.scalar(select(Room).where(Room.id == room_id).options(selectinload(Room.members)))
    decisions = list(await s.scalars(select(Decision).where(Decision.room_id == room_id).order_by(Decision.id)))
    questions = await s.scalars(
        select(OpenQuestion)
        .where(OpenQuestion.room_id == room_id, OpenQuestion.resolved.is_(False))
        .order_by(OpenQuestion.id)
    )
    tasks = await s.scalars(
        select(Task)
        .where(Task.room_id == room_id, Task.status != TaskStatus.cancelled)
        .options(selectinload(Task.assignee))
        .order_by(Task.id)
    )
    return {
        "room": room.name,
        "objective": room.objective,
        "summary": room.summary,
        "boss": boss_display_name(),
        "members": [{"name": e.name, "title": e.title} for e in room.members],
        "decisions": {
            status.value: [
                {"id": d.id, "title": d.title, "rationale": d.rationale, "proposed_by": d.proposed_by}
                for d in decisions
                if d.status == status
            ]
            for status in DecisionStatus
        },
        "open_questions": [
            {"id": q.id, "question": q.question, "asked_by": q.asked_by} for q in questions
        ],
        "who_does_what": [
            {
                "task_id": t.id,
                "title": t.title,
                "kind": t.kind.value,
                "status": t.status.value,
                "assignee": t.assignee.name if t.assignee else None,
            }
            for t in tasks
        ],
    }


async def add_decision(
    s: AsyncSession, project_id: int, room_id: int, title: str, rationale: str, author: Employee
) -> Decision:
    decision = Decision(room_id=room_id, title=title, rationale=rationale, proposed_by=author.name)
    s.add(decision)
    await s.flush()
    emit_event(s, project_id, "decision_proposed", {"room_id": room_id, "decision_id": decision.id}, role="boss")
    await s.commit()
    return decision


async def update_summary(s: AsyncSession, room_id: int, summary: str) -> None:
    room = await s.get(Room, room_id)
    room.summary = summary
    await s.commit()


async def add_question(s: AsyncSession, room_id: int, question: str, author: Employee) -> OpenQuestion:
    q = OpenQuestion(room_id=room_id, question=question, asked_by=author.name)
    s.add(q)
    await s.commit()
    return q


async def resolve_question(s: AsyncSession, room_id: int, question_id: int, answer: str) -> None:
    q = await s.get(OpenQuestion, question_id)
    if q is None or q.room_id != room_id:
        raise WorkflowError(f"No open question #{question_id} in this room")
    q.answer = answer
    q.resolved = True
    await s.commit()


# --- Notes and escalation ----------------------------------------------------------


async def read_notes(s: AsyncSession, employee_id: int) -> str:
    note = await s.get(Note, employee_id)
    return note.content if note else ""


async def write_notes(s: AsyncSession, employee_id: int, content: str, append: bool) -> str:
    note = await s.get(Note, employee_id)
    if note is None:
        note = Note(employee_id=employee_id, content="")
        s.add(note)
    note.content = f"{note.content.rstrip()}\n{content}".strip() if append else content
    await s.commit()
    return note.content


async def escalate(
    s: AsyncSession, project_id: int, conversation_id: int, author: Employee, to: str, reason: str
) -> Message:
    target = "boss" if to == "boss" else "lead"
    if target == "boss":
        name = boss_name() or "boss"
    else:
        employees = await s.scalars(select(Employee).where(Employee.project_id == project_id))
        name = next((e.name for e in employees if "lead" in e.roles), "lead")
    # Written like any message to them; the escalation event is what routes it
    content = reason if f"@{name}".lower() in reason.lower() else f"@{name} {reason}"
    msg = await post_message(s, project_id, conversation_id, content, author)
    emit_event(
        s,
        project_id,
        "escalation",
        {"conversation_id": conversation_id, "message_id": msg.id, "from": author.name},
        role=target,
    )
    await s.commit()
    return msg
