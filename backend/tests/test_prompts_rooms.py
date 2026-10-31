"""Wakeup prompt: the employee's channels and DMs, and the DM/group/decision rules."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import services
from app.models import Base, Employee, Project, Room
from app.orchestrator.prompts import operating_rules, rooms_section, wake_prompt


def test_wake_prompt_lists_rooms():
    prompt = wake_prompt(["mention"], [("#general", "team"), ("@Mehdi", "dm")])
    assert "- #general\n" in prompt + "\n"
    assert "- @Mehdi (DM)" in prompt


def test_wake_prompt_without_rooms_is_unchanged():
    assert wake_prompt(["a", "a"]) == "You are being woken up because:\n- a"
    assert rooms_section([]) is None


def test_common_rules_cover_dm_group_and_decisions():
    assert "DM is for an exchange between two people" in operating_rules()
    assert "concerns several people goes in a group" in operating_rules()
    assert "Never decide anything in a DM" in operating_rules()


def test_rules_say_the_boss_only_sees_direction_and_presence():
    rules = operating_rules()
    assert "see only that channel and whether each of you is busy or available" in rules
    assert "read every other channel" not in rules and "can also read DMs" not in rules
    assert "{" not in rules


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def test_rooms_of_on_a_real_database_names_dms_after_the_other_person(db):
    project, other = (Project(name=n, repo_url=f"https://github.com/o/{n}", mode="enterprise", seed=i) for i, n in enumerate("ab"))
    db.add_all([project, other])
    await db.flush()
    me, maya, kenji = (Employee(project_id=project.id, name=n, title=n, roles=["dev_backend"], model="m", permissions=[], traits={}, quirks=[], style={}, mcp_token=str(i)) for i, n in enumerate(("Malik", "Maya", "Kenji")))
    stranger = Employee(project_id=other.id, name="Zed", title="Zed", roles=["dev_backend"], model="m", permissions=[], traits={}, quirks=[], style={}, mcp_token="z")
    db.add_all([me, maya, kenji, stranger])
    await db.flush()
    db.add_all([
        Room(project_id=project.id, name="general", kind="team", members=[me, maya, kenji]),
        Room(project_id=project.id, name="Malik·Maya", kind="dm", members=[me, maya]),
        Room(project_id=project.id, name="Maya·Kenji", kind="dm", members=[maya, kenji]),
        Room(project_id=project.id, name="ops", kind="team", members=[maya]),
        Room(project_id=other.id, name="general", kind="team", members=[stranger]),
    ])  # fmt: skip
    await db.commit()
    db.expunge_all()  # members must come from the query itself, not the identity map
    me, maya = (await db.scalars(select(Employee).where(Employee.name.in_(["Malik", "Maya"])).order_by(Employee.id))).all()

    assert await services.rooms_of(db, me) == [("#general", "team"), ("@Maya", "dm")]
    assert await services.rooms_of(db, maya) == [
        ("#general", "team"), ("@Malik", "dm"), ("@Kenji", "dm"), ("#ops", "team")
    ]  # fmt: skip
