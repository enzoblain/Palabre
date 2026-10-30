"""Presence: open run, finished run, employee never launched."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import AgentRun, Base, Employee, Project
from app.presence import team_presence

T1 = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    async def execute(self, _query):
        self.calls += 1
        return Result(self.rows)


def row(id, name, kind=None, task_id=None, conversation_id=None, started_at=None, last=None):
    return SimpleNamespace(
        id=id, name=name, roles=["dev"], kind=kind, task_id=task_id,
        conversation_id=conversation_id, started_at=started_at, last_run_at=last,
    )  # fmt: skip


async def test_open_finished_and_never_launched():
    s = FakeSession([
        row(1, "Ann", "task", task_id=7, started_at=T2, last=T2),
        row(2, "Bob", last=T1),
        row(3, "Cy"),
    ])  # fmt: skip
    ann, bob, cy = await team_presence(s, 1)
    assert s.calls == 1
    assert (ann["state"], ann["kind"], ann["task_id"], ann["last_run_at"]) == ("working", "task", 7, T2)
    assert (bob["state"], bob["kind"], bob["last_run_at"]) == ("idle", None, T1)
    assert (cy["state"], cy["last_run_at"]) == ("idle", None)


async def test_most_recent_open_run_wins():
    s = FakeSession([
        row(1, "Ann", "task", task_id=7, started_at=T1, last=T2),
        row(1, "Ann", "conversation", conversation_id=4, started_at=T2, last=T2),
    ])  # fmt: skip
    (ann,) = await team_presence(s, 1)
    assert (ann["kind"], ann["conversation_id"], ann["task_id"]) == ("conversation", 4, None)


# --- Real SQL (in-memory SQLite): the outer join and the max() subquery ---------------------


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def test_real_query_open_finished_and_never_launched(db):
    db.add_all([
        Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1),
        Project(name="Other", repo_url="https://github.com/o/s", mode="enterprise", seed=2),
    ])  # fmt: skip
    await db.flush()
    ann, bob, cy, zed = (
        Employee(project_id=pid, name=n, roles=["dev"], title="Dev", model="m", permissions=[], traits={},
                 quirks=[], style={}, mcp_token=n)
        for pid, n in ((1, "Ann"), (1, "Bob"), (1, "Cy"), (2, "Zed"))
    )  # fmt: skip
    db.add_all([ann, bob, cy, zed])
    await db.flush()
    db.add_all([
        AgentRun(employee_id=ann.id, kind="conversation", started_at=T1, finished_at=T1),
        AgentRun(employee_id=ann.id, kind="task", started_at=T2),
        AgentRun(employee_id=bob.id, kind="task", started_at=T1, finished_at=T2),
        AgentRun(employee_id=zed.id, kind="task", started_at=T2),
    ])  # fmt: skip
    await db.flush()
    result = await team_presence(db, 1)
    assert [e["name"] for e in result] == ["Ann", "Bob", "Cy"]
    a, b, c = result
    assert (a["state"], a["kind"], _utc(a["last_run_at"])) == ("working", "task", T2)
    assert (b["state"], b["kind"], _utc(b["last_run_at"])) == ("idle", None, T1)
    assert (c["state"], c["last_run_at"]) == ("idle", None)


def _utc(d):
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def test_endpoint_requires_auth():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/projects/1/presence").status_code == 401
