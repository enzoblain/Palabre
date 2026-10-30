"""The unread summary endpoint, on a real in-memory database."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import services
from app.api import conversations
from app.models import Base, Conversation, Employee, Message, Project, Room


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1))
        session.add(Project(name="Q", repo_url="https://github.com/o/q", mode="enterprise", seed=2))
        await session.flush()
        session.add(Employee(project_id=1, name="Malik", roles=["dev"], title="Dev", model="m", permissions=[],
                             traits={}, quirks=[], style={}, mcp_token="m"))  # fmt: skip
        session.add_all([
            Room(id=1, project_id=1, name="direction", kind="direction"),
            Room(id=2, project_id=1, name="a·b", kind="dm"),
            Room(id=3, project_id=2, name="other"),
        ])  # fmt: skip
        await session.flush()
        session.add_all([Conversation(id=i, room_id=i, title="c") for i in (1, 2, 3)] + [Conversation(id=4, room_id=1, title="empty")])
        await session.flush()
        msg = lambda c, e, text: Message(conversation_id=c, employee_id=e, author_name="x", content=text)  # noqa: E731
        session.add_all([msg(1, 1, "a"), msg(1, None, "boss"), msg(2, 1, "dm"), msg(3, 1, "elsewhere")])
        await session.flush()
        yield session
    await engine.dispose()


async def test_summary_lists_the_project_conversations(db):
    out = {i.conversation_id: i for i in await conversations.unread_summary(1, db)}
    assert set(out) == {1, 2, 4}
    assert (out[1].last_id, out[1].last_employee_id) == (2, 1)  # the boss's message is the latest, not unread
    assert (out[4].last_id, out[4].last_employee_id) == (0, 0)


async def test_summary_hides_dms_when_boss_does_not_read_them(db, monkeypatch):
    monkeypatch.setattr(services, "BOSS_READS_DMS", False)
    assert {i.conversation_id for i in await conversations.unread_summary(1, db)} == {1, 4}


async def test_summary_404_on_unknown_project(db):
    with pytest.raises(Exception) as exc:
        await conversations.unread_summary(99, db)
    assert exc.value.status_code == 404
