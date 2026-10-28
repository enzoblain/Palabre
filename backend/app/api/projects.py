from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app import github, projects
from app.accounts import account_count
from app.api.deps import SessionDep, get_or_404
from app.api.schemas import (
    EmployeeDetail,
    EmployeeOut,
    EmployeePatch,
    ModeChange,
    ProjectDetail,
    ProjectIn,
    ProjectOut,
)
from app.company.team import load_catalog, render_system_prompt
from app.models import Employee, Project
from app.services import boss_display_name

router = APIRouter(tags=["projects"])


async def _project(s, project_id: int) -> Project:
    project = await projects.load_project(s, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Project {project_id} not found")
    return project


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(s: SessionDep):
    return list(await s.scalars(select(Project).order_by(Project.id)))


@router.post("/projects", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectIn, s: SessionDep):
    """Create a project: the team is drawn at random for the chosen mode."""
    if body.mode not in load_catalog()["modes"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown mode: {body.mode}")
    try:
        github.repo_slug(body.repo_url)
    except github.GitHubError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    _check_accounts(body.accounts.values())
    project = await projects.create_project(s, **body.model_dump())
    return await _project(s, project.id)


def _check_accounts(accounts) -> None:
    n = account_count()
    if any(not 1 <= a <= n for a in accounts):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Account must be between 1 and {n} (CLAUDE_CODE_OAUTH_TOKENS)"
        )


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: int, s: SessionDep):
    return await _project(s, project_id)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: int, s: SessionDep):
    await s.delete(await get_or_404(s, Project, project_id))
    await s.commit()


@router.put("/projects/{project_id}/mode", response_model=ProjectDetail)
async def change_mode(project_id: int, body: ModeChange, s: SessionDep):
    """Grow or shrink the company (e.g. startup → scaleup)."""
    if body.mode not in load_catalog()["modes"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown mode: {body.mode}")
    return await projects.change_mode(s, await _project(s, project_id), body.mode)


# --- Employees ---------------------------------------------------------------------


@router.get("/projects/{project_id}/employees", response_model=list[EmployeeOut])
async def list_employees(project_id: int, s: SessionDep):
    return (await _project(s, project_id)).employees


@router.get("/employees/{employee_id}", response_model=EmployeeDetail)
async def get_employee(employee_id: int, s: SessionDep):
    """An employee, with the system prompt they run with."""
    employee = await get_or_404(s, Employee, employee_id)
    team = projects.team_of(await _project(s, employee.project_id))
    member = next(m for m in team.employees if m.name == employee.name)
    return EmployeeDetail.model_validate(
        {**EmployeeOut.model_validate(employee).model_dump(), "system_prompt": render_system_prompt(team, member, boss_display_name())}
    )


@router.patch("/employees/{employee_id}", response_model=EmployeeOut)
async def update_employee(employee_id: int, body: EmployeePatch, s: SessionDep):
    """Edit an employee's personality, model or Claude account by hand."""
    employee = await get_or_404(s, Employee, employee_id)
    projects.validate_personality(body.traits, body.style)
    for field, value in body.model_dump(exclude_none=True, exclude={"account"}).items():
        setattr(employee, field, value)
    if "account" in body.model_fields_set:  # null puts the employee back in the automatic spread
        if body.account is not None:
            _check_accounts([body.account])
        employee.account = body.account
    await s.commit()
    return employee


@router.post("/employees/{employee_id}/reroll", response_model=EmployeeOut)
async def reroll_employee(employee_id: int, s: SessionDep):
    """Draw a new random personality (name and roles are kept)."""
    return await projects.reroll_personality(s, await get_or_404(s, Employee, employee_id))
