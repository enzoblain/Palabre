"""REST endpoints for projects."""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app import github, projects
from app.accounts import account_count
from app.api.deps import SessionDep, get_or_404
from app.api.schemas import (
    EmployeeDetail,
    EmployeeOut,
    EmployeePatch,
    BranchChange,
    MemberIn,
    ModeChange,
    ProjectDetail,
    ProjectIn,
    ProjectOut,
)
from app.company.team import kind_of_mode, load_catalog, render_system_prompt
from app.models import Employee, Project
from app.orchestrator.dispatcher import orchestrator
from app.worktrees import remove_project_files
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
    """Create a project: a company on a GitHub repository, or a research group on a topic
    (the mode says which). The team is drawn at random for the mode, or built by hand."""
    if body.mode not in load_catalog()["modes"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown mode: {body.mode}")
    kind = kind_of_mode(body.mode)
    if kind == "research":
        if not (body.topic or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A research project needs a topic")
    else:
        try:
            await github.resolve_branch(github.repo_slug(body.repo_url), "")  # fail early on an unreachable repository
        except github.GitHubError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    _check_accounts(body.accounts.values())
    if body.employees is not None:
        _check_team(body.employees, kind)
    project = await projects.create_project(s, **body.model_dump())
    return await _project(s, project.id)


def _check_team(employees: list[MemberIn], kind: str) -> None:
    """A team built by hand: valid roles and personalities, unique names, and for a
    company a lead (they organize the work and merge)."""
    roles = {k for k, r in load_catalog()["roles"].items() if r["kind"] == kind}
    names = [e.name.lower() for e in employees]
    if len(set(names)) != len(names):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Two employees have the same name")
    for e in employees:
        if unknown := [r for r in e.roles if r not in roles]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{e.name}: unknown roles {', '.join(unknown)}")
        projects.validate_personality(e.traits, e.style, partial=True, kind=kind)
    if kind == "company" and not any("lead" in e.roles for e in employees):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The team needs a lead (they organize and merge)")
    _check_accounts([e.account for e in employees if e.account is not None])


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
    """Delete a project and all its data: agents (their running work is stopped), rooms,
    messages, tasks, notes, files on disk and Claude sessions. The GitHub repository is
    left as it is."""
    project = await get_or_404(s, Project, project_id)
    employee_ids = list(await s.scalars(select(Employee.id).where(Employee.project_id == project_id)))
    await orchestrator.cancel_runs(employee_ids)
    await s.delete(project)
    await s.commit()
    await remove_project_files(project_id)


@router.put("/projects/{project_id}/mode", response_model=ProjectDetail)
async def change_mode(project_id: int, body: ModeChange, s: SessionDep):
    """Grow or shrink the company (e.g. startup → scaleup)."""
    project = await _project(s, project_id)
    if body.mode not in load_catalog()["modes"] or kind_of_mode(body.mode) != project.kind:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown {project.kind} mode: {body.mode}")
    return await projects.change_mode(s, project, body.mode)



@router.put("/projects/{project_id}/branch", response_model=ProjectDetail)
async def change_branch(project_id: int, body: BranchChange, s: SessionDep):
    """The branch the team works from and merges into (created on GitHub if missing)."""
    project = await _project(s, project_id)
    if project.kind != "company":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A research project has no repository")
    if body.branch == project.default_branch:
        return project
    return await projects.change_branch(s, project, body.branch)


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
    project = await get_or_404(s, Project, employee.project_id)
    projects.validate_personality(body.traits, body.style, kind=project.kind)
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
