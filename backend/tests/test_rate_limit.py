"""Anti-loop limit on a real in-memory database: only executed runs count, and the boss can lift it."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models import AgentRun, Base, Conversation, Employee, Event, Project, Room
from app.orchestrator.dispatcher import Orchestrator, SkipRun


@pytest.fixture
async def db(monkeypatch):
    monkeypatch.setattr(settings, "max_runs_per_conversation_hour", 2)
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1))
        await session.flush()
        session.add(Employee(project_id=1, name="Malik", roles=["dev"], title="Dev", model="m", permissions=[],
                             traits={}, quirks=[], style={}, mcp_token="m"))  # fmt: skip
        session.add(Room(project_id=1, name="r"))
        await session.flush()
        session.add(Conversation(room_id=1, title="c"))
        await session.flush()
        yield session
    await engine.dispose()


def add_run(s, error=None, finished=True, ago=timedelta(minutes=5)):
    s.add(
        AgentRun(employee_id=1, kind="wakeup", conversation_id=1, started_at=datetime.now(UTC) - ago,
                 finished_at=datetime.now(UTC) if finished else None, error=error, ok=None)
    )  # fmt: skip


async def check(s, orch=None):
    await (orch or Orchestrator())._check_rate(s, SimpleNamespace(id=1), 1, 999, {"mention"})


async def count_seen(s):
    """The run count _check_rate reports when it refuses."""
    with pytest.raises(SkipRun) as exc:
        await check(s)
    return int(str(exc.value).split()[0])


async def test_skipped_queued_and_done_and_running_runs(db):
    add_run(db, error="skipped: 3 review rounds")
    add_run(db, error="skipped: usage limit reached, wakeups queued")
    add_run(db)  # Succeeded
    add_run(db, finished=False)  # Still running
    await db.flush()
    assert await count_seen(db) == 2


async def test_below_the_limit_the_wakeup_passes(db):
    add_run(db, error="skipped: x")
    add_run(db)
    await db.flush()
    await check(db)


async def test_lifting_the_limit_survives_a_restart(db):
    add_run(db)
    add_run(db)
    await db.flush()
    with pytest.raises(SkipRun):
        await check(db)
    await Orchestrator().lift_rate_limit(db, 1, 1)
    event = await db.scalar(select(Event).where(Event.type == "rate_limit_lifted"))
    assert event.processed_at is not None  # Nobody gets woken for it
    await check(db, Orchestrator())  # A fresh orchestrator, as after a restart
    add_run(db, ago=timedelta(0))
    add_run(db, ago=timedelta(0))
    await db.flush()
    with pytest.raises(SkipRun):
        await check(db)
