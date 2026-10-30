"""Anti-loop limit on a real in-memory database: only executed runs count, and the boss can lift it."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models import AgentRun, Base, Conversation, Employee, Event, Project, Room, Wakeup
from app.orchestrator.dispatcher import Orchestrator, Throttled


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
    await (orch or Orchestrator())._check_rate(s, SimpleNamespace(id=1), 1, 1, 999, {"mention"})


async def count_seen(s):
    """The run count _check_rate reports when it refuses."""
    with pytest.raises(Throttled) as exc:
        await check(s)
    return int(str(exc.value).split()[0])


async def test_skipped_queued_and_done_and_running_runs(db):
    add_run(db, error="skipped: 3 review rounds")
    add_run(db, error="skipped: usage limit reached, wakeups queued")
    add_run(db)  # Succeeded
    add_run(db, finished=False)  # Still running
    await db.flush()
    assert await count_seen(db) == 2


async def test_limit_zero_with_a_recent_run_defers_instead_of_crashing(db, monkeypatch):
    monkeypatch.setattr(settings, "max_runs_per_conversation_hour", 0)
    add_run(db)
    await db.flush()
    with pytest.raises(Throttled) as exc:
        await check(db)  # Used to raise IndexError
    assert timedelta(minutes=59) < exc.value.until - datetime.now(UTC) <= timedelta(hours=1)


async def test_below_the_limit_the_wakeup_passes(db):
    add_run(db, error="skipped: x")
    add_run(db)
    await db.flush()
    await check(db)


async def test_lifting_the_limit_survives_a_restart(db):
    add_run(db)
    add_run(db)
    await db.flush()
    with pytest.raises(Throttled):
        await check(db)
    await Orchestrator().lift_rate_limit(db, 1, 1)
    event = await db.scalar(select(Event).where(Event.type == "rate_limit_lifted"))
    assert event.processed_at is not None  # Nobody gets woken for it
    await check(db, Orchestrator())  # A fresh orchestrator, as after a restart
    add_run(db, ago=timedelta(0))
    add_run(db, ago=timedelta(0))
    await db.flush()
    with pytest.raises(Throttled):
        await check(db)


async def test_counter_is_per_employee_across_conversations(db):
    db.add(Employee(project_id=1, name="Zoe", roles=["dev"], title="Dev", model="m", permissions=[],
                    traits={}, quirks=[], style={}, mcp_token="z"))  # fmt: skip
    db.add(Conversation(room_id=1, title="c2"))
    await db.flush()
    add_run(db)
    db.add(AgentRun(employee_id=1, kind="wakeup", conversation_id=2, started_at=datetime.now(UTC), ok=None))
    db.add(AgentRun(employee_id=2, kind="wakeup", conversation_id=1, started_at=datetime.now(UTC), ok=None))
    await db.flush()
    with pytest.raises(Throttled):
        await check(db)  # employee 1: two runs in two conversations
    await Orchestrator()._check_rate(db, SimpleNamespace(id=1), 2, 1, 999, {"mention"})  # employee 2: one run


async def test_throttled_wakeup_waits_then_runs_when_the_window_frees(db, monkeypatch):
    add_run(db, ago=timedelta(minutes=50))
    add_run(db, ago=timedelta(minutes=5))
    await db.flush()
    with pytest.raises(Throttled) as exc:
        await check(db)
    # The oldest run leaves the hour in ~10 minutes
    wait = exc.value.until - datetime.now(UTC)
    assert timedelta(minutes=9) < wait < timedelta(minutes=11)

    w = [Wakeup(employee_id=1, event_type="mention", kind="conversation", conversation_id=1, reason=f"r{i}") for i in range(2)]
    db.add_all(w)
    await db.flush()
    run = AgentRun(employee_id=1, kind="conversation", conversation_id=1)
    db.add(run)
    await db.flush()
    await Orchestrator()._defer(db, run.id, [x.id for x in w], exc.value)
    await db.refresh(w[0])
    assert w[0].started_at is None and w[0].finished_at is None  # Not lost
    assert w[0].not_before.replace(tzinfo=UTC) == exc.value.until


async def test_dispatch_picks_only_ready_wakeups_and_groups_them(db, monkeypatch):
    from app.orchestrator import dispatcher

    now = datetime.now(UTC)
    mk = lambda reason, nb=None: Wakeup(employee_id=1, event_type="mention", kind="conversation",  # noqa: E731
                                        conversation_id=1, reason=reason, not_before=nb)  # fmt: skip
    db.add_all([mk("future", now + timedelta(minutes=10)), mk("past", now - timedelta(minutes=1)), mk("fresh")])
    await db.flush()
    await db.commit()
    monkeypatch.setattr(dispatcher, "SessionLocal", lambda: _Same(db))
    monkeypatch.setattr(dispatcher, "credits", SimpleNamespace(is_exhausted=lambda a: False))
    orch = Orchestrator()
    got = []

    async def fake_run(employee_id, ids):
        got.append(ids)

    monkeypatch.setattr(orch, "_run", fake_run)
    await orch._dispatch()
    await asyncio.gather(*orch._runs.values())
    assert got == [[2, 3]]  # The held one stays out; the other two run in one batch
    held = await db.get(Wakeup, 1)
    assert held.started_at is None

    held.not_before = now - timedelta(seconds=1)  # The window freed up
    await db.commit()
    await orch._dispatch()
    await asyncio.gather(*orch._runs.values())
    assert got == [[2, 3], [1]]


class _Same:
    """Hands the test session to code that opens its own, without closing it."""

    def __init__(self, s):
        self.s = s

    async def __aenter__(self):
        return self.s

    async def __aexit__(self, *a):
        return False
