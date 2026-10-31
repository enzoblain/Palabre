"""Rooms: no generic channel at creation, and the startup migration that removes the old ones."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import projects
from app.company.team import generate_team
from app.models import Base, Conversation, Employee, Message, Project, Room, Task
from app.projects import RESEARCH_ROOM, drop_generic_rooms, load_project


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
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
    await add_room(db, project, "dev", emps[:2])
    await add_room(db, project, "direction", [emps[0]], kind="direction")
    await add_room(db, project, "Malik-Nathan", emps[:2], kind="dm", messages=3)
    # same name as a generic room, but not its composition: someone's own channel
    await add_room(db, project, "product", emps[:2])
    await db.commit()

    await drop_generic_rooms(db)
    assert await names(db) == {"dev", "direction", "Malik-Nathan", "product"}
    kept = await db.scalar(select(func.count()).select_from(Message))
    assert kept == 1 + 3 + 1 + 1  # dev, dm, direction, product; none of the deleted rooms' messages

    await drop_generic_rooms(db)  # idempotent
    assert await names(db) == {"dev", "direction", "Malik-Nathan", "product"}


async def test_a_generic_room_with_tasks_is_kept(db):
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
