"""REST endpoints for projects."""

from fastapi import APIRouter, status
from sqlalchemy import select

from app import github, presence, projects
from app.accounts import account_count
from app.api.deps import SessionDep, get_or_404
from app.api.errors import ApiError, ErrorCode
from app.api.schemas import (
    EmployeeDetail,
    EmployeeOut,
    EmployeePatch,
    LastMessageOut,
    BranchChange,
    MemberIn,
    ModeChange,
    PresenceOut,
    ProjectDetail,
    ProjectIn,
    ProjectListItem,
    ProjectOut,
    ProjectPatch,
    ProjectUpdated,
    ProjectsDelete,
)
from app.company.catalog import MANDATORY_ROLE, MIN_TEAM_SIZE, load_catalog, team_permission_error
from app.company.team import render_system_prompt
from app.models import Employee, Message, Project
from app.orchestrator.dispatcher import orchestrator
from app.worktrees import remove_project_files
from app import services
from app.services import boss_display_name

router = APIRouter(tags=["projects"])


async def _project(s, project_id: int) -> Project:
    project = await projects.load_project(s, project_id)
    if project is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, f"Project {project_id} not found"
        )
    return project


def _detail(project: Project) -> ProjectDetail:
    """The project's payload; its rooms are only what the boss sees (same rule as list_rooms)."""
    detail = ProjectDetail.model_validate(project)
    detail.rooms = [r for r in detail.rooms if r.kind == services.DIRECTION]
    return detail


def _list_item(project: Project, unread: int, writing: bool, last_message: Message | None) -> ProjectListItem:
    return ProjectListItem(
        **ProjectOut.model_validate(project).model_dump(),
        unread_count=unread,
        lead_writing=writing,
        last_message=LastMessageOut(content=last_message.content, author=last_message.author_name, created_at=last_message.created_at)
        if last_message
        else None,
    )


@router.get("/projects", response_model=list[ProjectListItem])
async def list_projects(s: SessionDep):
    """Projects, with the unread messages of direction, the latest one, and whether the lead is answering in it."""
    unread, writing = await services.unread_counts(s), await presence.leads_writing(s)
    last_messages = await services.last_direction_messages(s)
    items = await s.scalars(select(Project).order_by(Project.id))
    return [_list_item(p, unread.get(p.id, 0), p.id in writing, last_messages.get(p.id)) for p in items]


@router.post("/projects/{project_id}/direction/read", response_model=ProjectListItem)
async def mark_direction_read(project_id: int, s: SessionDep):
    """The boss has read direction up to now: the unread counter goes back to 0."""
    project = await get_or_404(s, Project, project_id)
    await services.mark_direction_read(s, project)
    last_message = (await services.last_direction_messages(s)).get(project.id)
    return _list_item(project, 0, project.id in await presence.leads_writing(s), last_message)


@router.post("/projects", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectIn, s: SessionDep):
    """Create a project: a company on a GitHub repository. The team is drawn at random for the
    mode, or built by hand."""
    if body.mode not in load_catalog()["modes"]:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.UNKNOWN_MODE, f"Unknown mode: {body.mode}"
        )
    try:
        await github.resolve_branch(github.repo_slug(body.repo_url), "")  # fail early on an unreachable repository
    except github.GitHubError as exc:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.INVALID_REPOSITORY,
            str(exc),
        ) from None
    _check_creation_mode(body)
    _check_accounts(body.accounts.values())
    if body.employees is not None:
        _check_team(body.employees)
    project = await projects.create_project(s, **body.model_dump())
    if body.employees:
        projects.plan_custom_channels_later(project.id)
    return _detail(await _project(s, project.id))


def _invalid_creation(code: ErrorCode, message: str) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


def _check_creation_mode(body: ProjectIn) -> None:
    """Manual: the team is listed, has at least MIN_TEAM_SIZE members and holds the mandatory
    member. Automatic: a description and at least MIN_TEAM_SIZE employees, no list."""
    if body.creation_mode is None:
        return
    if body.creation_mode == "manual":
        if body.employees is None:  # a listed team is checked by `_check_team`
            raise _invalid_creation(ErrorCode.LEAD_REQUIRED, f"A manual team is listed and holds the {MANDATORY_ROLE}")
        if len(body.employees) < MIN_TEAM_SIZE:
            raise _invalid_creation(
                ErrorCode.TEAM_TOO_SMALL, f"A manual team needs at least {MIN_TEAM_SIZE} members"
            )
        return
    if body.employees is not None:
        raise _invalid_creation(ErrorCode.INVALID_CREATION_MODE, "An automatic team is not listed by hand")
    if not (body.description or "").strip():
        raise _invalid_creation(ErrorCode.INVALID_CREATION_MODE, "An automatic team needs a project description")
    if body.employee_count is None or body.employee_count < MIN_TEAM_SIZE:
        raise _invalid_creation(
            ErrorCode.TEAM_TOO_SMALL, f"An automatic team needs at least {MIN_TEAM_SIZE} employees"
        )


def _check_team(employees: list[MemberIn]) -> None:
    """A team built by hand: valid roles and personalities, unique names, for a company a
    lead (they organize the work and merge), and the permission rules of the catalog."""
    catalog = load_catalog()
    roles = catalog["roles"]
    presets = catalog["personalities"]
    names = [e.name.lower() for e in employees]
    if len(set(names)) != len(names):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.DUPLICATE_EMPLOYEE_NAME,
            "Two employees have the same name",
        )
    for e in employees:
        if unknown := [r for r in e.roles if r not in roles]:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ErrorCode.UNKNOWN_ROLES,
                f"{e.name}: unknown roles {', '.join(unknown)}",
            )
        projects.validate_personality(e.traits, e.style, partial=True)
        if e.personality is not None and e.personality not in presets:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ErrorCode.UNKNOWN_PERSONALITY,
                f"{e.name}: unknown personality {e.personality}",
            )
    if not any(MANDATORY_ROLE in e.roles for e in employees):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.LEAD_REQUIRED,
            f"The team needs a {MANDATORY_ROLE} (they organize and merge)",
        )
    if problem := team_permission_error([e.roles for e in employees]):
        raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.INVALID_TEAM_PERMISSIONS, problem)
    _check_accounts([e.account for e in employees if e.account is not None])


def _check_accounts(accounts) -> None:
    n = account_count()
    if any(not 1 <= a <= n for a in accounts):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.INVALID_ACCOUNT,
            f"Account must be between 1 and {n} (CLAUDE_CODE_OAUTH_TOKENS)",
        )


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: int, s: SessionDep):
    return _detail(await _project(s, project_id))


def _check_main_branch_allowed(project: Project, branch: str) -> None:
    """The team's branch or a task branch as main would send agent merges straight to production."""
    if branch == project.default_branch:
        reason = "it is the team's working branch"
    elif github.is_task_branch_name(branch):
        reason = "it is a task branch"
    else:
        return
    raise ApiError(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.INVALID_MAIN_BRANCH,
        f"The branch '{branch}' cannot be the main branch: {reason}",
    )


@router.patch("/projects/{project_id}", response_model=ProjectUpdated)
async def update_project(project_id: int, body: ProjectPatch, s: SessionDep):
    """Rename a project and/or change its main (production) branch, which must already exist
    on GitHub (422 `github_branch_missing` otherwise; 422 `invalid_main_branch` for the team's branch or a task branch; no branch is created or deleted). The
    `warning` says so when the team still works on the previous main branch. The description
    and the GitHub repository cannot be edited."""
    project = await _project(s, project_id)
    warning = None
    if body.main_branch is not None:
        _check_main_branch_allowed(project, body.main_branch)
        if not await github.branch_exists(github.repo_slug(project.repo_url), body.main_branch):
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                ErrorCode.GITHUB_BRANCH_MISSING,
                f"The branch '{body.main_branch}' does not exist on GitHub",
            )
        warning = await projects.change_main_branch(project, body.main_branch)
    if body.name is not None:
        project.name = body.name
        await s.commit()
    return ProjectUpdated(**_detail(project).model_dump(), warning=warning)


async def _delete_project_data(s, project: Project) -> None:
    employee_ids = list(await s.scalars(select(Employee.id).where(Employee.project_id == project.id)))
    await s.delete(project)
    await s.commit()
    # Rows first, so the dispatcher cannot start a new run that recreates a desk after the files are gone
    await orchestrator.cancel_runs(employee_ids)
    await remove_project_files(project.id)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: int, s: SessionDep):
    """Delete a project and all its data: agents (their running work is stopped), rooms,
    messages, tasks, notes, files on disk and Claude sessions. The GitHub repository is
    left as it is."""
    await _delete_project_data(s, await get_or_404(s, Project, project_id))


@router.post("/projects/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_projects(body: ProjectsDelete, s: SessionDep):
    """Delete several projects like `DELETE /projects/{id}`. Nothing is deleted if one id is unknown (404)."""
    found = {p.id: p for p in await s.scalars(select(Project).where(Project.id.in_(body.ids)))}
    if missing := sorted(set(body.ids) - found.keys()):
        raise ApiError(
            status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, f"Projects not found: {', '.join(map(str, missing))}"
        )
    for project in found.values():
        await _delete_project_data(s, project)


@router.put("/projects/{project_id}/mode", response_model=ProjectDetail)
async def change_mode(project_id: int, body: ModeChange, s: SessionDep):
    """Grow or shrink the company (e.g. startup → scaleup)."""
    project = await _project(s, project_id)
    if body.mode not in load_catalog()["modes"]:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorCode.UNKNOWN_MODE,
            f"Unknown mode: {body.mode}",
        )
    return _detail(await projects.change_mode(s, project, body.mode))



@router.put("/projects/{project_id}/branch", response_model=ProjectDetail)
async def change_branch(project_id: int, body: BranchChange, s: SessionDep):
    """The branch the team works from and merges into (created on GitHub if missing)."""
    project = await _project(s, project_id)
    if body.branch == project.default_branch:
        return _detail(project)
    return _detail(await projects.change_branch(s, project, body.branch))


# --- Employees ---------------------------------------------------------------------


@router.get("/projects/{project_id}/employees", response_model=list[EmployeeOut])
async def list_employees(project_id: int, s: SessionDep):
    return (await _project(s, project_id)).employees


@router.get("/projects/{project_id}/presence", response_model=list[PresenceOut])
async def team_presence(project_id: int, s: SessionDep):
    """Who is working (open run, with its task or conversation) and who is idle; the front polls it."""
    await get_or_404(s, Project, project_id)
    return await presence.team_presence(s, project_id)


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
