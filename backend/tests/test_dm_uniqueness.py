"""DMs against a real SQL engine (SQLite): one room per pair, even when two first messages race."""

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import services
from app.api import conversations, rooms
from app.db import upgrade_schema
from app.models import Base, Conversation, Employee, Project, Room
from app.orchestrator.prompts import reason_for


@pytest.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def seed(maker):
    async with maker() as s:
        s.add(Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1))
        await s.flush()
        s.add_all([Employee(project_id=1, name=n, roles=["dev_backend"], title="Dev", model="m", permissions=[], traits={},
                     quirks=[], style={}, mcp_token=n)
            for n in ("Malik", "Maya")])
        await s.commit()


async def test_second_creation_loses_the_race_and_rereads_the_room(maker):
    await seed(maker)
    async with maker() as a, maker() as b:
        malik, maya = [await a.get(Employee, i) for i in (1, 2)]
        malik_b, maya_b = [await b.get(Employee, i) for i in (1, 2)]
        first = await services.get_or_create_dm(a, 1, malik, "@Maya")
        # b looked before a committed: simulate by hiding the room from its first lookup
        real_scalar, calls = b.scalar, []

        async def blind_scalar(q, *args, **kw):
            calls.append(q)
            return None if len(calls) == 2 else await real_scalar(q, *args, **kw)

        b.scalar = blind_scalar
        await a.commit()
        second = await services.get_or_create_dm(b, 1, maya_b, "@Malik")
    assert first == second
    async with maker() as s:
        assert await s.scalar(select(func.count(Room.id)).where(Room.kind == "dm")) == 1


async def test_index_rejects_a_duplicate_dm_but_not_team_rooms(maker):
    from sqlalchemy.exc import IntegrityError

    async with maker() as s:
        s.add_all([Room(project_id=1, name="x", kind="team"), Room(project_id=1, name="x", kind="team")])
        await s.commit()
        s.add_all([Room(project_id=1, name="a·b", kind="dm"), Room(project_id=1, name="a·b", kind="dm")])
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_upgrade_adds_the_index_on_an_existing_table():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("DROP INDEX uq_rooms_dm_name")
        await conn.run_sync(upgrade_schema)
        await conn.run_sync(upgrade_schema)  # idempotent
        names = (await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'index'")).scalars().all()
        assert "uq_rooms_dm_name" in names
    await engine.dispose()


async def test_boss_cannot_read_dms_by_id_when_disabled(maker, monkeypatch):
    await seed(maker)
    async with maker() as s:
        room = Room(project_id=1, name="Malik·Maya", kind="dm")
        s.add(room)
        await s.flush()
        conv = Conversation(room_id=room.id, title="DM")
        s.add(conv)
        await s.commit()
        assert (await conversations.get_conversation(conv.id, s)).id == conv.id
        monkeypatch.setattr(services, "BOSS_READS_DMS", False)
        for call in (
            conversations.get_conversation(conv.id, s),
            conversations.list_messages(conv.id, s, None, 10),
            conversations.list_conversations(room.id, s),
            rooms.get_room(room.id, s),
        ):
            with pytest.raises(HTTPException) as exc:
                await call
            assert exc.value.status_code == 404


def test_dm_wakeup_has_its_own_sentence():
    text = reason_for("mention", {"message_id": 4, "dm": True, "from": "Maya"})
    assert "Maya" in text and "direct message" in text
    assert "mentioned" in reason_for("mention", {"message_id": 4})
