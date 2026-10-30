"""Context reset every N finished tasks: counter, threshold, off at 0, what is kept."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app import workflow
from app.models import AgentSession, Base, Employee, Project, Review, Task, TaskStatus, Verdict
from app.db import upgrade_schema
from app.orchestrator import context_reset
from app.orchestrator.dispatcher import Orchestrator


class FakeDb:
    """Counts the finished tasks it is told about; records deletions and commits."""

    def __init__(self, finished: int):
        self.finished, self.executed, self.commits = finished, [], 0

    async def scalar(self, _query):
        return self.finished

    async def execute(self, query):
        self.executed.append(str(query))

    async def commit(self):
        self.commits += 1


def employee():
    return SimpleNamespace(id=1, name="Malik", context_reset_at=None, created_at=None)


@pytest.fixture(autouse=True)
def every_five(monkeypatch):
    monkeypatch.setattr(settings, "context_reset_every_tasks", 5)


async def test_counter_is_read_from_the_database():
    assert await context_reset.finished_tasks_since_reset(FakeDb(3), employee()) == 3


async def test_below_threshold_nothing_happens():
    s, who = FakeDb(4), employee()
    assert not await context_reset.reset_context_if_due(s, who)
    assert s.executed == [] and who.context_reset_at is None


@pytest.mark.parametrize("finished", [5, 7])
async def test_at_threshold_sessions_are_deleted_and_counter_restarts(finished):
    s, who = FakeDb(finished), employee()
    assert await context_reset.reset_context_if_due(s, who)
    assert len(s.executed) == 1 and s.executed[0].startswith("DELETE FROM agent_sessions")
    assert who.context_reset_at is not None and s.commits == 1


async def test_only_agent_sessions_are_deleted():
    s = FakeDb(5)
    await context_reset.reset_context_if_due(s, employee())
    assert [q for q in s.executed if "notes" in q or "tasks" in q or "messages" in q] == []


async def test_zero_disables_the_reset(monkeypatch):
    monkeypatch.setattr(settings, "context_reset_every_tasks", 0)
    s, who = FakeDb(50), employee()
    assert not await context_reset.reset_context_if_due(s, who)
    assert s.executed == [] and who.context_reset_at is None


# --- Who counts: reviewers, QA, security and the lead -------------------------------------


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def seed(s):
    """A project with one employee plus a colleague, and a helper to add tasks."""
    s.add(Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1))
    await s.flush()
    people = [
        Employee(project_id=1, name=n, roles=["dev"], title="Dev", model="m", permissions=[], traits={}, quirks=[],
                 style={}, mcp_token=n)
        for n in ("Malik", "Nathan")
    ]  # fmt: skip
    s.add_all(people)
    await s.flush()
    return people


def add_task(s, title, **fields):
    task = Task(project_id=1, room_id=1, conversation_id=1, title=title, **fields)
    s.add(task)
    return task


async def test_assigned_reviewed_and_merged_tasks_each_count_once(db):
    malik, nathan = await seed(db)
    now = datetime.now(UTC)
    add_task(db, "assigned", status=TaskStatus.done, assignee_id=malik.id, closed_at=now)
    reviewed = add_task(db, "reviewed", status=TaskStatus.done, assignee_id=nathan.id, closed_at=now)
    add_task(db, "merged", status=TaskStatus.cancelled, assignee_id=nathan.id, closed_by_id=malik.id, closed_at=now)
    add_task(db, "open", status=TaskStatus.review, assignee_id=malik.id)
    add_task(db, "someone else's", status=TaskStatus.done, assignee_id=nathan.id, closed_at=now)
    await db.flush()
    for round in (1, 2):
        db.add(Review(task_id=reviewed.id, reviewer_id=malik.id, verdict=Verdict.approve, round=round, body=""))
    await db.flush()
    assert await context_reset.finished_tasks_since_reset(db, malik) == 3


async def test_a_late_edit_of_an_old_task_is_not_counted_again(db):
    malik, _ = await seed(db)
    malik.context_reset_at = datetime.now(UTC)
    old = add_task(db, "old", status=TaskStatus.done, assignee_id=malik.id, closed_at=malik.context_reset_at - timedelta(days=1))
    await db.flush()
    old.title = "touched later"  # bumps updated_at
    await db.flush()
    assert await context_reset.finished_tasks_since_reset(db, malik) == 0


def lead_flow(monkeypatch):
    from tests.conftest import make_employee, make_task

    task = make_task(project_id=1, depends_on=[], title="T", conversation_id=1, pr_url=None, pr_title="feat: x", closed_by_id=None, closed_at=None)
    lead = make_employee("Élise", "lead")

    async def get_task(*_):
        return task

    async def nothing(*_, **__):
        pass

    for name in ("clean_up_task", "announce", "merge_blockers"):
        monkeypatch.setattr(workflow, name, nothing)

    async def merge_pull_request(*_):
        pass

    monkeypatch.setattr(workflow, "get_task", get_task)
    monkeypatch.setattr(workflow.github, "merge_pull_request", merge_pull_request)
    return task, lead


class WorkflowDb(FakeDb):
    async def get(self, *_):
        from tests.conftest import make_project

        return make_project()

    async def scalars(self, _query):
        return []

    def add(self, _obj):
        pass

    async def flush(self):
        pass


async def test_the_lead_is_recorded_at_merge(monkeypatch):
    task, lead = lead_flow(monkeypatch)

    async def post_message(*_):
        pass

    monkeypatch.setattr(workflow, "post_message", post_message)
    await workflow.merge_task(WorkflowDb(0), 1, task.id, lead, force=True)
    assert task.closed_by_id == lead.id and task.closed_at is not None


async def test_the_boss_merging_is_recorded_as_nobody(monkeypatch):
    task, _ = lead_flow(monkeypatch)
    task.closed_by_id = 99
    await workflow.merge_task(WorkflowDb(0), 1, task.id, None, force=True)
    assert task.closed_by_id is None


async def test_the_lead_is_recorded_when_cancelling(monkeypatch):
    task, lead = lead_flow(monkeypatch)
    await workflow.update_task(
        WorkflowDb(0), 1, task.id, title=None, description=None, acceptance_criteria=None,
        depends_on=None, status="cancelled", author=lead,
    )  # fmt: skip
    assert task.closed_by_id == lead.id and task.closed_at is not None


# --- Per-session reset every N runs -------------------------------------------------------


async def test_a_worn_session_is_not_resumed_but_the_others_are(db, monkeypatch):
    monkeypatch.setattr(settings, "context_reset_every_runs", 5)
    malik, _ = await seed(db)
    db.add_all([
        AgentSession(employee_id=malik.id, scope="task:1", claude_session_id="a", runs=5),
        AgentSession(employee_id=malik.id, scope="task:2", claude_session_id="b", runs=4),
    ])  # fmt: skip
    await db.flush()
    assert await context_reset.reset_session_if_worn(db, malik, "task:1")
    assert not await context_reset.reset_session_if_worn(db, malik, "task:2")
    assert await db.get(AgentSession, (malik.id, "task:1")) is None
    assert (await db.get(AgentSession, (malik.id, "task:2"))).claude_session_id == "b"


async def test_no_session_or_zero_means_nothing_to_reset(db, monkeypatch):
    monkeypatch.setattr(settings, "context_reset_every_runs", 5)
    malik, _ = await seed(db)
    assert not await context_reset.reset_session_if_worn(db, malik, "task:1")
    db.add(AgentSession(employee_id=malik.id, scope="task:1", claude_session_id="a", runs=50))
    await db.flush()
    monkeypatch.setattr(settings, "context_reset_every_runs", 0)
    assert not await context_reset.reset_session_if_worn(db, malik, "task:1")
    assert await db.get(AgentSession, (malik.id, "task:1")) is not None


async def test_only_task_runs_resume_their_session(db):
    malik, _ = await seed(db)
    db.add_all([
        AgentSession(employee_id=malik.id, scope="task:1", claude_session_id="t", runs=2),
        AgentSession(employee_id=malik.id, scope="conversation:1", claude_session_id="c", runs=2),
    ])  # fmt: skip
    await db.flush()
    resume = Orchestrator._session_to_resume
    assert await resume(db, malik, "task:1") == "t"
    assert await resume(db, malik, "conversation:1") is None
    assert await resume(db, malik, "task:2") is None


async def test_conversation_scopes_store_no_session(db, monkeypatch):
    monkeypatch.setattr(settings, "context_reset_every_runs", 1)
    malik, _ = await seed(db)
    await Orchestrator()._save_session(db, malik.id, "conversation:1", "a", resumed=False)
    assert await db.get(AgentSession, (malik.id, "conversation:1")) is None
    assert not await context_reset.reset_session_if_worn(db, malik, "conversation:1")


async def test_default_is_five():
    assert type(settings).model_fields["context_reset_every_runs"].default == 5


# --- Run counter and one-time purge -------------------------------------------------------


async def test_save_session_counts_runs(db):
    malik, _ = await seed(db)
    orch = Orchestrator()
    await orch._save_session(db, malik.id, "task:1", "a", resumed=False)
    assert (await db.get(AgentSession, (malik.id, "task:1"))).runs == 1
    await orch._save_session(db, malik.id, "task:1", "a", resumed=True)
    assert (await db.get(AgentSession, (malik.id, "task:1"))).runs == 2
    await orch._save_session(db, malik.id, "task:1", "b", resumed=False)
    session = await db.get(AgentSession, (malik.id, "task:1"))
    assert (session.runs, session.claude_session_id) == (1, "b")


async def test_upgrade_drops_sessions_once_when_runs_column_is_added():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql("DROP TABLE agent_sessions")
        await conn.exec_driver_sql(
            "CREATE TABLE agent_sessions (employee_id INTEGER, scope VARCHAR, claude_session_id VARCHAR,"
            " PRIMARY KEY (employee_id, scope))"
        )
        await conn.exec_driver_sql("INSERT INTO agent_sessions VALUES (1, 'task:1', 'old')")
        await conn.run_sync(upgrade_schema)
        assert (await conn.exec_driver_sql("SELECT count(*) FROM agent_sessions")).scalar() == 0
        await conn.exec_driver_sql("INSERT INTO agent_sessions (employee_id, scope, claude_session_id) VALUES (1, 'task:1', 'new')")
        await conn.run_sync(upgrade_schema)  # a restart
        assert (await conn.exec_driver_sql("SELECT count(*) FROM agent_sessions")).scalar() == 1
    await engine.dispose()


async def test_upgrade_deletes_legacy_conversation_sessions():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.exec_driver_sql(
            "INSERT INTO agent_sessions (employee_id, scope, claude_session_id) VALUES (1, 'conversation:1', 'c'), (1, 'task:1', 't')"
        )
        await conn.run_sync(upgrade_schema)
        await conn.run_sync(upgrade_schema)  # idempotent
        rows = (await conn.exec_driver_sql("SELECT scope FROM agent_sessions")).scalars().all()
        assert rows == ["task:1"]
    await engine.dispose()
