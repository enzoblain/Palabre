"""Adding, removing and changing the members of a running team through the API."""

from dataclasses import asdict

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import projects as api
from app.api.errors import ApiError, ErrorCode
from app.api.schemas import EmployeeIn, EmployeePatch
from app.company.catalog import MAX_TEAM_SIZE, MIN_TEAM_SIZE, load_catalog
from app.company.team import custom_employee
from app.errors import WorkflowError
from app.models import Base, Conversation, Employee, Message, Project, Review, Room, Task, TaskStatus, Verdict


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def enforce_foreign_keys(connection, _record):  # Like PostgreSQL: ON DELETE rules really run
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def cancelled(monkeypatch):
    ids: list[int] = []

    async def cancel_runs(employee_ids):
        ids.extend(employee_ids)

    monkeypatch.setattr(api.orchestrator, "cancel_runs", cancel_runs)
    return ids


async def _team(s, role_sets=(("lead",), ("dev_backend",), ("dev_backend",), ("reviewer",))) -> Project:
    project = Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1)
    names = ["Ada", "Bob", "Cleo", "Dan", "Eve", "Fay"]
    project.employees = [
        Employee(**vars_of(custom_employee(list(roles), names[i])), mcp_token=f"t{i}")
        for i, roles in enumerate(role_sets)
    ]
    s.add(project)
    await s.flush()
    dev = Room(project=project, name="dev", members=[project.employees[1], project.employees[2]])
    s.add(dev)
    await s.commit()
    return await api.projects.load_project(s, project.id)


def vars_of(member) -> dict:
    return asdict(member)


def _by_name(project: Project, name: str) -> Employee:
    return next(e for e in project.employees if e.name == name)


async def test_add_member_joins_default_channels(db):
    project = await _team(db)
    out = await api.add_employee(project.id, EmployeeIn(name="Zed", roles=["dev_backend"]), db)
    assert out.name == "Zed" and out.roles == ["dev_backend"]
    project = await api.projects.load_project(db, project.id)
    dev = next(r for r in project.rooms if r.name == "dev")
    assert "Zed" in {m.name for m in dev.members}


async def test_add_member_draws_a_unique_name_and_applies_the_preset(db):
    project = await _team(db)
    preset = next(iter(load_catalog()["personalities"]))
    out = await api.add_employee(project.id, EmployeeIn(roles=["qa"], personality=preset), db)
    assert out.name not in {"Ada", "Bob", "Cleo", "Dan"}
    expected = load_catalog()["personalities"][preset]
    assert out.quirks == list(expected["quirks"])


async def test_add_member_refuses_a_duplicate_name_case_insensitively(db):
    project = await _team(db)
    with pytest.raises(WorkflowError) as error:
        await api.add_employee(project.id, EmployeeIn(name="bob", roles=["qa"]), db)
    assert error.value.code == ErrorCode.DUPLICATE_EMPLOYEE_NAME


async def test_add_member_refuses_unknown_role_and_preset(db):
    project = await _team(db)
    with pytest.raises(WorkflowError) as error:
        await api.add_employee(project.id, EmployeeIn(roles=["nope"]), db)
    assert error.value.code == ErrorCode.UNKNOWN_ROLES
    with pytest.raises(WorkflowError) as error:
        await api.add_employee(project.id, EmployeeIn(roles=["qa"], personality="nope"), db)
    assert error.value.code == ErrorCode.UNKNOWN_PERSONALITY


async def test_add_a_second_lead_is_refused(db):
    project = await _team(db)
    with pytest.raises(WorkflowError) as error:
        await api.add_employee(project.id, EmployeeIn(roles=["lead"]), db)
    assert error.value.code == ErrorCode.INVALID_TEAM_PERMISSIONS


async def test_add_member_refuses_a_full_team(db):
    project = await _team(db)
    project.employees.extend(
        Employee(**vars_of(custom_employee(["qa"], f"N{i}")), mcp_token=f"x{i}")
        for i in range(MAX_TEAM_SIZE - len(project.employees))
    )
    await db.commit()
    with pytest.raises(WorkflowError) as error:
        await api.add_employee(project.id, EmployeeIn(roles=["qa"]), db)
    assert error.value.code == ErrorCode.TEAM_TOO_LARGE


async def test_remove_member_unassigns_open_tasks_and_keeps_messages(db, cancelled):
    project = await _team(db, (("lead",), ("dev_backend",), ("dev_backend",), ("reviewer",), ("qa",)))
    bob = _by_name(project, "Bob")
    room = project.rooms[0]
    conversation = Conversation(room_id=room.id, title="c")
    db.add(conversation)
    await db.flush()
    db.add(Message(conversation_id=conversation.id, employee_id=bob.id, author_name="Bob", content="hello"))
    where = {"project_id": project.id, "room_id": room.id, "conversation_id": conversation.id}
    open_task = Task(**where, title="a", assignee_id=bob.id, created_by_id=bob.id, status=TaskStatus.in_progress)
    done_task = Task(**where, title="b", assignee_id=bob.id, status=TaskStatus.done)
    db.add_all([open_task, done_task])
    await db.commit()
    bob_id = bob.id

    await api.remove_employee(bob_id, db)

    await db.refresh(open_task)
    await db.refresh(done_task)
    assert (open_task.assignee_id, open_task.status) == (None, TaskStatus.todo)
    assert done_task.status == TaskStatus.done
    assert await db.get(Employee, bob_id) is None
    message = await db.get(Message, 1)
    assert (message.content, message.author_name) == ("hello", "Bob")
    assert message.employee_id == bob_id  # Not NULL: NULL would read as the boss
    assert open_task.created_by_id == bob_id
    project = await api.projects.load_project(db, project.id)
    assert "Bob" not in {m.name for r in project.rooms for m in r.members}
    assert cancelled == [bob_id]


async def test_remove_the_lead_is_refused(db, cancelled):
    project = await _team(db, (("lead",), ("dev_backend",), ("reviewer",), ("qa",), ("qa",)))
    with pytest.raises(WorkflowError) as error:
        await api.remove_employee(_by_name(project, "Ada").id, db)
    assert error.value.code == ErrorCode.LEAD_PROTECTED
    assert cancelled == []


async def test_remove_below_the_minimum_size_is_refused(db, cancelled):
    project = await _team(db)
    assert len(project.employees) == MIN_TEAM_SIZE
    with pytest.raises(WorkflowError) as error:
        await api.remove_employee(_by_name(project, "Dan").id, db)
    assert error.value.code == ErrorCode.TEAM_TOO_SMALL
    assert cancelled == []


async def test_change_role_renews_permissions_and_channels(db):
    project = await _team(db)
    bob = _by_name(project, "Bob")
    out = await api.update_employee(bob.id, EmployeePatch(roles=["qa"]), db)
    assert out.roles == ["qa"]
    assert out.permissions == custom_employee(["qa"], "x").permissions
    project = await api.projects.load_project(db, project.id)
    dev = next(r for r in project.rooms if r.name == "dev")
    assert "Bob" not in {m.name for m in dev.members}


async def test_change_role_to_one_without_code_unassigns_open_tasks(db):
    project = await _team(db)
    bob = _by_name(project, "Bob")
    room_id = project.rooms[0].id
    conversation = Conversation(room_id=room_id, title="c")
    db.add(conversation)
    await db.flush()
    where = dict(project_id=project.id, room_id=room_id, conversation_id=conversation.id)
    open_task = Task(**where, title="a", assignee_id=bob.id, status=TaskStatus.in_progress)
    done_task = Task(**where, title="b", assignee_id=bob.id, status=TaskStatus.done)
    db.add_all([open_task, done_task])
    await db.commit()
    await api.update_employee(bob.id, EmployeePatch(roles=["qa"]), db)
    assert (open_task.assignee_id, open_task.status) == (None, TaskStatus.todo)
    assert done_task.assignee_id == bob.id


async def test_change_role_to_one_with_code_keeps_open_tasks(db):
    project = await _team(db)
    bob = _by_name(project, "Bob")
    room_id = project.rooms[0].id
    conversation = Conversation(room_id=room_id, title="c")
    db.add(conversation)
    await db.flush()
    task = Task(
        project_id=project.id, room_id=room_id, conversation_id=conversation.id, title="a",
        assignee_id=bob.id, status=TaskStatus.in_progress,
    )  # fmt: skip
    db.add(task)
    await db.commit()
    await api.update_employee(bob.id, EmployeePatch(roles=["dev_frontend"]), db)
    assert (task.assignee_id, task.status) == (bob.id, TaskStatus.in_progress)


async def test_change_role_of_the_lead_is_refused(db):
    project = await _team(db)
    with pytest.raises(WorkflowError) as error:
        await api.update_employee(_by_name(project, "Ada").id, EmployeePatch(roles=["dev"]), db)
    assert error.value.code == ErrorCode.LEAD_PROTECTED


async def test_change_role_to_lead_is_refused(db):
    project = await _team(db)
    with pytest.raises(WorkflowError) as error:
        await api.update_employee(_by_name(project, "Bob").id, EmployeePatch(roles=["lead"]), db)
    assert error.value.code == ErrorCode.LEAD_ALREADY_EXISTS
    assert _by_name(project, "Bob").roles == ["dev_backend"]
    assert _by_name(project, "Ada").roles == ["lead"]


async def test_change_personality_of_the_lead_is_allowed(db):
    project = await _team(db)
    preset = next(iter(load_catalog()["personalities"]))
    out = await api.update_employee(_by_name(project, "Ada").id, EmployeePatch(personality=preset), db)
    assert out.quirks == list(load_catalog()["personalities"][preset]["quirks"])
    assert out.roles == ["lead"]


async def test_unknown_employee_is_404(db):
    with pytest.raises(ApiError) as error:
        await api.remove_employee(999, db)
    assert error.value.status_code == 404


async def test_remove_member_deletes_their_dms_and_withdraws_their_reviews(db):
    project = await _team(db, (("lead",), ("dev_backend",), ("dev_backend",), ("reviewer",), ("qa",), ("dev_backend",)))
    bob, cleo, dan = (_by_name(project, n) for n in ("Bob", "Cleo", "Dan"))
    dm_with_bob = Room(project_id=project.id, name="Bob·Cleo", kind="dm", members=[bob, cleo])
    dm_other = Room(project_id=project.id, name="Cleo·Dan", kind="dm", members=[cleo, dan])
    conversation = Conversation(room_id=project.rooms[0].id, title="c")
    db.add_all([dm_with_bob, dm_other, conversation])
    await db.flush()
    task = Task(
        project_id=project.id, room_id=project.rooms[0].id, conversation_id=conversation.id, title="a",
        status=TaskStatus.review,
    )  # fmt: skip
    db.add(task)
    await db.flush()
    review = Review(task_id=task.id, reviewer_id=dan.id, verdict=Verdict.approve, round=1, body="ok")
    db.add(review)
    await db.commit()
    bob_id, dm_with_bob_id, dm_other_id, dan_id, review_id = bob.id, dm_with_bob.id, dm_other.id, dan.id, review.id

    await api.remove_employee(dan_id, db)
    assert await db.get(Review, review_id) is None
    assert await db.get(Room, dm_other_id) is None

    await api.remove_employee(bob_id, db)
    assert await db.get(Room, dm_with_bob_id) is None


async def test_add_a_second_lead_is_refused(db):
    project = await _team(db)
    with pytest.raises(WorkflowError) as error:
        await api.add_employee(project.id, EmployeeIn(name="Zed", roles=["lead"]), db)
    assert error.value.code == ErrorCode.LEAD_ALREADY_EXISTS
    project = await api.projects.load_project(db, project.id)
    assert len(project.employees) == 4
    assert _by_name(project, "Ada").roles == ["lead"]
