"""Rooms: no generic channel at creation, and the startup migration that removes the old ones."""

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import projects
from app.company.team import generate_team
from app.models import Base, Conversation, Decision, Employee, Message, OpenQuestion, Project, Room, Task
from app.projects import RESEARCH_ROOM, drop_generic_rooms, load_project


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enforce_foreign_keys(conn, _):  # SQLite ignores ON DELETE CASCADE otherwise, as Postgres does not
        conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def make_project(s, mode="enterprise", kind="company") -> Project:
    team = generate_team(mode, 1)
    project = Project(name="P", repo_url="https://github.com/o/r", mode=mode, seed=1, kind=kind)
    project.employees = [Employee(**e.__dict__, mcp_token=f"{e.name}{mode}") for e in team.employees]
    s.add(project)
    await s.flush()
    return await load_project(s, project.id)  # rooms loaded: no lazy IO later


async def add_room(s, project, name, members, kind="team", messages=1) -> Room:
    room = Room(project=project, name=name, kind=kind, members=members)
    s.add(room)
    await s.flush()
    conversation = Conversation(room_id=room.id, title="Kickoff")
    s.add(conversation)
    await s.flush()
    for i in range(messages):
        s.add(Message(conversation_id=conversation.id, author_name="Boss", content=f"m{i}"))
    await s.flush()
    return room


async def names(s) -> set[str]:
    return set(await s.scalars(select(Room.name)))


async def test_predefined_team_only_gets_the_catalog_channels(db):
    project = await make_project(db)
    await projects._open_channels(db, project)
    catalog = {c["name"] for c in projects.load_catalog()["channels"]}
    assert {r.name for r in project.rooms} <= catalog
    assert not {"general", "engineering", "product"} & {r.name for r in project.rooms}


async def test_custom_team_starts_with_no_channel_but_direction(db):
    project = await make_project(db)
    await projects.ensure_direction(db, project)  # create_project opens no channel for a custom team
    assert {r.name for r in project.rooms} == {"direction"}


async def test_generic_rooms_go_with_their_messages_and_the_rest_stays(db):
    project = await make_project(db)
    everyone, emps = list(project.employees), project.employees
    await add_room(db, project, "general", everyone)
    await add_room(db, project, "equipe", everyone)
    await add_room(db, project, "engineering", emps[:3])  # it gained or lost members since: still generic
    await add_room(db, project, "dev", emps[:2])
    await add_room(db, project, "direction", [emps[0]], kind="direction")
    await add_room(db, project, "Malik-Nathan", emps[:2], kind="dm", messages=3)
    await add_room(db, project, "general", emps[:2], kind="dm", messages=2)  # a DM is never touched
    await db.commit()

    await drop_generic_rooms(db)
    assert await names(db) == {"dev", "direction", "Malik-Nathan", "general"}
    assert await db.scalar(select(Room.kind).where(Room.name == "general")) == "dm"
    kept = await db.scalar(select(func.count()).select_from(Message))
    assert kept == 1 + 1 + 3 + 2  # dev, direction, both DMs; none of the deleted rooms' messages

    await drop_generic_rooms(db)  # idempotent
    assert await names(db) == {"dev", "direction", "Malik-Nathan", "general"}
    assert await db.scalar(select(func.count()).select_from(Message)) == kept


async def test_tasks_decisions_and_questions_move_to_direction(db):
    project = await make_project(db)
    emps = project.employees
    general = await add_room(db, project, "general", list(emps))
    direction = await add_room(db, project, "direction", [emps[0]], kind="direction")
    general_conversation = await db.scalar(select(Conversation.id).where(Conversation.room_id == general.id))
    direction_conversation = await db.scalar(select(Conversation.id).where(Conversation.room_id == direction.id))
    task = Task(project_id=project.id, room_id=general.id, conversation_id=general_conversation, title="t")
    decision = Decision(room_id=general.id, title="Release 1.0", proposed_by="Élise", pr_number=7)
    question = OpenQuestion(room_id=general.id, question="why?", asked_by="Élise")
    db.add_all([task, decision, question])
    await db.commit()

    await drop_generic_rooms(db)
    await db.refresh(task)
    await db.refresh(decision)
    await db.refresh(question)
    assert await names(db) == {"direction"}
    assert (task.room_id, task.conversation_id) == (direction.id, direction_conversation)
    assert decision.room_id == direction.id and decision.pr_number == 7
    assert question.room_id == direction.id


async def test_a_generic_room_holding_tasks_is_kept_without_a_direction_room(db):
    project = await make_project(db)
    room = await add_room(db, project, "general", list(project.employees))
    db.add(Task(project_id=project.id, room_id=room.id, conversation_id=1, title="t"))
    await db.commit()
    await drop_generic_rooms(db)
    assert await names(db) == {"general"}


async def test_research_general_room_is_renamed_not_deleted(db):
    project = await make_project(db, mode="duo", kind="research")
    await add_room(db, project, "general", list(project.employees))
    await db.commit()
    await drop_generic_rooms(db)
    assert await names(db) == {RESEARCH_ROOM}
    await drop_generic_rooms(db)
    assert await names(db) == {RESEARCH_ROOM}


async def test_change_mode_newcomers_join_a_migrated_research_room(db):
    project = await make_project(db, mode="duo", kind="research")
    await add_room(db, project, "general", list(project.employees))
    await db.commit()
    await drop_generic_rooms(db)
    project = await load_project(db, project.id)
    assert [r.name for r in project.rooms] == [RESEARCH_ROOM]  # what change_mode matches on


def test_no_cleanup_path_touches_dms():
    """Only the admin delete removes a room, and it refuses a DM; nothing else deletes rooms."""
    from pathlib import Path

    app = Path(projects.__file__).parent
    hits = [
        p.name for p in app.rglob("*.py")
        if "delete(Room)" in (text := p.read_text()) or "s.delete(room)" in text
    ]  # fmt: skip
    assert sorted(hits) == ["projects.py", "rooms.py"]
