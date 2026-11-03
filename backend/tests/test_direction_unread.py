"""Unread messages of direction per project, and the lead's "writing" indicator."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import presence, services
from app.config import settings
from app.models import AgentRun, Base, Conversation, Employee, Message, Project, Room


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def _project(s, name: str = "P"):
    project = Project(name=name, repo_url="https://github.com/o/r", mode="enterprise", seed=1)
    s.add(project)
    await s.flush()
    lead = Employee(project_id=project.id, name="Louise", title="Lead", model="opus", permissions=[], traits={}, quirks=[], style={}, roles=["lead"], mcp_token=name)
    team_room = Room(project_id=project.id, name="team", kind="team")
    direction = Room(project_id=project.id, name="direction", kind="direction")
    s.add_all([lead, team_room, direction])
    await s.flush()
    direction_conversation = Conversation(room_id=direction.id, title="General")
    team_conversation = Conversation(room_id=team_room.id, title="General")
    s.add_all([direction_conversation, team_conversation])
    await s.flush()
    return project, lead, direction_conversation, team_conversation


def _say(conversation, author: Employee | None, system: bool = False) -> Message:
    return Message(
        conversation_id=conversation.id, employee_id=author.id if author else None,
        author_name=author.name if author else "Boss", content="hi", is_system=system,
    )  # fmt: skip


async def test_only_the_leads_messages_in_direction_are_unread(db):
    project, lead, direction, team = await _project(db)
    db.add_all([_say(direction, lead), _say(direction, lead), _say(direction, None), _say(direction, None, system=True), _say(team, lead)])
    await db.flush()
    assert await services.unread_counts(db) == {project.id: 2}


async def test_mark_read_resets_the_counter_and_new_messages_count_again(db):
    project, lead, direction, _ = await _project(db)
    other, other_lead, other_direction, _ = await _project(db, "Q")
    db.add_all([_say(direction, lead), _say(other_direction, other_lead)])
    await db.flush()
    await services.mark_direction_read(db, project)
    assert await services.unread_counts(db) == {other.id: 1}
    db.add(_say(direction, lead))
    await db.flush()
    assert (await services.unread_counts(db))[project.id] == 1


async def test_mark_read_without_messages_keeps_zero(db):
    project, *_ = await _project(db)
    await services.mark_direction_read(db, project)
    assert project.boss_read_message_id == 0


def _run(lead: Employee, conversation: Conversation, **kwargs) -> AgentRun:
    return AgentRun(employee_id=lead.id, kind="conversation", conversation_id=conversation.id, **kwargs)


async def test_lead_writing_while_a_run_is_open_in_direction(db):
    project, lead, direction, team = await _project(db)
    other, other_lead, _, other_team = await _project(db, "Q")
    db.add_all([_run(lead, direction), _run(other_lead, other_team)])
    await db.flush()
    assert await presence.leads_writing(db) == {project.id}


async def test_lead_not_writing_when_the_run_is_over_or_orphan(db):
    project, lead, direction, _ = await _project(db)
    other, other_lead, other_direction, _ = await _project(db, "Q")
    orphan_start = datetime.now(UTC) - timedelta(seconds=settings.agent_timeout_s + 60)
    db.add_all([
        _run(lead, direction, finished_at=datetime.now(UTC)),
        _run(other_lead, other_direction, started_at=orphan_start),
    ])  # fmt: skip
    await db.flush()
    assert await presence.leads_writing(db) == set()


@pytest.fixture
async def api(db):
    from httpx import ASGITransport, AsyncClient

    from app.db import get_session
    from app.main import app

    async def session():
        yield db

    app.dependency_overrides[get_session] = session
    headers = {"Authorization": f"Bearer {settings.admin_token}"}
    transport = ASGITransport(app=app, client=("4.4.4.4", 1))
    async with AsyncClient(transport=transport, base_url="http://t", headers=headers) as client:
        yield client
    app.dependency_overrides.pop(get_session, None)


async def test_project_list_exposes_unread_count_and_lead_writing(db, api):
    project, lead, direction, _ = await _project(db)
    db.add_all([_say(direction, lead), _say(direction, lead), _run(lead, direction)])
    await db.flush()
    response = await api.get("/api/projects")
    assert response.status_code == 200
    item = next(p for p in response.json() if p["id"] == project.id)
    assert item["unread_count"] == 2
    assert item["lead_writing"] is True


async def test_mark_direction_read_endpoint_resets_the_counter(db, api):
    project, lead, direction, _ = await _project(db)
    db.add(_say(direction, lead))
    await db.flush()
    response = await api.post(f"/api/projects/{project.id}/direction/read")
    assert response.status_code == 200
    assert response.json()["unread_count"] == 0
    assert response.json()["lead_writing"] is False


async def test_mark_direction_read_unknown_project_is_404(api):
    response = await api.post("/api/projects/999/direction/read")
    assert response.status_code == 404


async def test_project_list_last_message_is_null_without_message(db, api):
    project, *_ = await _project(db)
    response = await api.get("/api/projects")
    item = next(p for p in response.json() if p["id"] == project.id)
    assert item["last_message"] is None


async def test_project_list_last_message_is_the_latest_of_direction_per_project(db, api):
    project, lead, direction, team = await _project(db)
    other, other_lead, other_direction, _ = await _project(db, "Q")
    last = _say(direction, None)
    last.content = "latest"
    db.add_all([_say(direction, lead), last, _say(team, lead), _say(other_direction, other_lead)])
    await db.flush()
    items = {p["id"]: p for p in (await api.get("/api/projects")).json()}
    assert items[project.id]["last_message"]["content"] == "latest"
    assert items[project.id]["last_message"]["author"] == "Boss"
    assert items[project.id]["last_message"]["created_at"]
    assert items[other.id]["last_message"]["author"] == "Louise"
