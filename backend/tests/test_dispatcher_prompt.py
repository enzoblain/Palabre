"""The system prompt assembled by the dispatcher carries the code standards (devs) or the checklist (reviewer)."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import AgentRun, Base, Conversation, Employee, Project, Room, Wakeup
from app.orchestrator import dispatcher
from app.orchestrator.dispatcher import Orchestrator
from app.orchestrator.prompts import STANDARD_POINTS


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1))
        await session.flush()
        for name, role in (("Malik", "dev_backend"), ("Nathan", "reviewer")):
            session.add(Employee(project_id=1, name=name, roles=[role], title=role, model="m", permissions=[],
                                 traits={}, quirks=[], style={}, mcp_token=name))  # fmt: skip
        session.add(Room(project_id=1, name="r"))
        await session.flush()
        session.add(Conversation(room_id=1, title="c"))
        await session.flush()
        yield session
    await engine.dispose()


async def system_prompt_of(db, monkeypatch, employee_id: int) -> str:
    async def no_check(*_):
        pass

    async def desk(*_):
        return "."

    orch = Orchestrator()
    monkeypatch.setattr(orch, "_check_rate", no_check)
    monkeypatch.setattr(orch, "_desk", desk)
    monkeypatch.setattr(dispatcher, "render_system_prompt", lambda *_: "persona")
    monkeypatch.setattr(dispatcher, "token_for", lambda _account: "token")
    wakeup = Wakeup(employee_id=employee_id, event_type="mention", kind="conversation", conversation_id=1, reason="r")
    run = AgentRun(employee_id=employee_id, kind="wakeup", conversation_id=1)
    db.add_all([wakeup, run])
    await db.flush()
    employee = await db.get(Employee, employee_id)
    spec, _ = await orch._prepare(db, employee, [wakeup], run.id)
    return spec.system_prompt


async def test_a_developer_run_gets_the_code_standards(db, monkeypatch):
    prompt = await system_prompt_of(db, monkeypatch, 1)
    assert "## Code standards" in prompt and "## Review checklist" not in prompt
    assert all(f"- {point}" in prompt for point in STANDARD_POINTS)


async def test_a_reviewer_run_gets_the_checklist_with_the_changes_verdict(db, monkeypatch):
    prompt = await system_prompt_of(db, monkeypatch, 2)
    assert "## Review checklist" in prompt and "## Code standards" not in prompt
    assert all(f"- {point}" in prompt for point in STANDARD_POINTS)
    assert "verdict `changes`" in prompt and "changes_requested" not in prompt
