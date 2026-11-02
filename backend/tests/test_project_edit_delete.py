"""Editing and deleting projects through the API."""

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import projects as api
from app.api.errors import ApiError, ErrorCode
from app.api.schemas import PROJECT_NAME_MAX_LENGTH, ProjectPatch, ProjectsDelete
from app.models import Base, Employee, Project


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def removed(monkeypatch):
    """Project ids whose files were removed and employee ids whose runs were cancelled."""
    files, cancelled = [], []

    async def remove_files(project_id):
        files.append(project_id)

    async def cancel_runs(employee_ids):
        cancelled.extend(employee_ids)

    monkeypatch.setattr(api, "remove_project_files", remove_files)
    monkeypatch.setattr(api.orchestrator, "cancel_runs", cancel_runs)
    return files, cancelled


async def _project(s, name: str = "P") -> Project:
    project = Project(name=name, repo_url="https://github.com/o/r", mode="enterprise", seed=1)
    project.employees = [
        Employee(
            name=f"{name}-lead", title="Lead", model="opus", permissions=[],
            traits={}, quirks=[], style={}, roles=["lead"], mcp_token=name,
        )  # fmt: skip
    ]
    s.add(project)
    await s.commit()
    return project


async def test_update_changes_the_name_only(db):
    project = await _project(db)
    detail = await api.update_project(project.id, ProjectPatch(name="  New  "), db)
    assert detail.name == "New"
    assert detail.repo_url == "https://github.com/o/r"


@pytest.mark.parametrize("fields", [{}, {"name": None}, {"main_branch": "bad branch"}, {"name": "   "}, {"name": ""}, {"name": "x" * (PROJECT_NAME_MAX_LENGTH + 1)}])
def test_update_refuses_an_invalid_name(fields):
    with pytest.raises(ValidationError):
        ProjectPatch(**fields)


async def test_update_unknown_project_is_404(db):
    with pytest.raises(ApiError) as error:
        await api.update_project(999, ProjectPatch(name="x"), db)
    assert error.value.status_code == 404


@pytest.fixture
def github_calls(monkeypatch):
    """Fake GitHub: `existing` branches, production `main`; records the default branch changes and clone follows."""
    calls = {"existing": {"main", "release"}, "default": [], "followed": []}

    async def branch_exists(repo, branch):
        return branch in calls["existing"]

    async def production_branch(repo):
        return "main"

    async def set_default_branch(repo, branch):
        calls["default"].append(branch)

    async def follow_main_branch(project, branch):
        calls["followed"].append(branch)

    monkeypatch.setattr(api.github, "branch_exists", branch_exists)
    monkeypatch.setattr(api.github, "production_branch", production_branch)
    monkeypatch.setattr(api.github, "set_default_branch", set_default_branch)
    monkeypatch.setattr(api.projects, "follow_main_branch", follow_main_branch)
    return calls


async def test_update_changes_the_main_branch(db, github_calls):
    project = await _project(db)
    project.default_branch = "dev"
    detail = await api.update_project(project.id, ProjectPatch(main_branch="release"), db)
    assert github_calls["default"] == ["release"] and github_calls["followed"] == ["release"]
    assert detail.warning is None and detail.default_branch == "dev"


async def test_update_warns_when_the_team_branch_was_the_main_branch(db, github_calls):
    project = await _project(db)
    project.default_branch = "main"
    detail = await api.update_project(project.id, ProjectPatch(main_branch="release"), db)
    assert "still works on main" in detail.warning
    assert detail.default_branch == "main"


async def test_update_refuses_a_branch_missing_on_github(db, github_calls):
    project = await _project(db)
    with pytest.raises(ApiError) as error:
        await api.update_project(project.id, ProjectPatch(main_branch="ghost", name="New"), db)
    assert error.value.status_code == 422 and error.value.code == ErrorCode.GITHUB_BRANCH_MISSING
    assert github_calls["default"] == [] and project.name == "P"


async def test_update_unknown_project_with_a_branch_is_404(db, github_calls):
    with pytest.raises(ApiError) as error:
        await api.update_project(999, ProjectPatch(main_branch="release"), db)
    assert error.value.status_code == 404


async def test_delete_removes_data_files_and_stops_runs(db, removed):
    project, other = await _project(db, "A"), await _project(db, "B")
    employee_ids = [e.id for e in project.employees]
    await api.delete_project(project.id, db)
    assert removed == ([project.id], employee_ids)
    assert list(await db.scalars(select(Project.id))) == [other.id]
    assert list(await db.scalars(select(Employee.project_id))) == [other.id]


async def test_delete_unknown_project_is_404(db, removed):
    with pytest.raises(ApiError) as error:
        await api.delete_project(999, db)
    assert error.value.status_code == 404
    assert removed == ([], [])


async def test_delete_several_projects(db, removed):
    first, second, kept = await _project(db, "A"), await _project(db, "B"), await _project(db, "C")
    await api.delete_projects(ProjectsDelete(ids=[first.id, second.id]), db)
    assert sorted(removed[0]) == [first.id, second.id]
    assert list(await db.scalars(select(Project.id))) == [kept.id]


async def test_delete_several_is_all_or_nothing(db, removed):
    project = await _project(db)
    with pytest.raises(ApiError) as error:
        await api.delete_projects(ProjectsDelete(ids=[project.id, 999]), db)
    assert error.value.status_code == 404
    assert list(await db.scalars(select(Project.id))) == [project.id]
    assert removed == ([], [])


def test_delete_several_needs_ids():
    with pytest.raises(ValidationError):
        ProjectsDelete(ids=[])


async def test_update_to_the_current_main_branch_still_syncs_the_clone(db, github_calls):
    project = await _project(db)
    project.default_branch = "dev"
    detail = await api.update_project(project.id, ProjectPatch(main_branch="main"), db)
    assert github_calls["default"] == [] and github_calls["followed"] == ["main"]
    assert detail.warning is None


@pytest.mark.parametrize("branch", ["dev", "task/429", "feat/12-main-branch"])
async def test_update_refuses_the_team_branch_and_task_branches_as_main(db, github_calls, branch):
    project = await _project(db)
    project.default_branch = "dev"
    github_calls["existing"].add(branch)
    with pytest.raises(ApiError) as error:
        await api.update_project(project.id, ProjectPatch(main_branch=branch, name="New"), db)
    assert error.value.status_code == 422 and error.value.code == ErrorCode.INVALID_MAIN_BRANCH
    assert github_calls["default"] == [] and github_calls["followed"] == [] and project.name == "P"
