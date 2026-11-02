"""Changes to a running team: add a member, remove one, change a role or a personality."""

import random
import secrets
from dataclasses import asdict

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app import projects, services
from app.company.catalog import (
    MANDATORY_ROLE,
    MAX_TEAM_SIZE,
    MIN_TEAM_SIZE,
    load_catalog,
    team_permission_error,
)
from app.company.team import custom_employee
from app.errors import ErrorCode, WorkflowError
from app.models import Employee, Project, Task, TaskStatus

CLOSED_STATUSES = (TaskStatus.done, TaskStatus.cancelled)


def _check_roles(roles: list[str]) -> None:
    unknown = [r for r in roles if r not in load_catalog()["roles"]]
    if unknown:
        raise WorkflowError(f"Unknown roles: {', '.join(unknown)}", code=ErrorCode.UNKNOWN_ROLES)


def _check_team_rules(roles_by_employee: list[list[str]]) -> None:
    if not any(MANDATORY_ROLE in roles for roles in roles_by_employee):
        raise WorkflowError(f"The team needs a {MANDATORY_ROLE}", code=ErrorCode.LEAD_REQUIRED)
    if problem := team_permission_error(roles_by_employee):
        raise WorkflowError(problem, code=ErrorCode.INVALID_TEAM_PERMISSIONS)


def _check_preset(preset: str | None) -> None:
    if preset is not None and preset not in load_catalog()["personalities"]:
        raise WorkflowError(f"Unknown personality: {preset}", code=ErrorCode.UNKNOWN_PERSONALITY)


def _free_name(project: Project, requested: str | None) -> str:
    taken = {e.name.lower() for e in project.employees}
    if requested is not None:
        if requested.lower() in taken:
            raise WorkflowError(f"The name {requested} is already used in this project", code=ErrorCode.DUPLICATE_EMPLOYEE_NAME)
        return requested
    free = sorted(n for n in load_catalog()["people"]["names"] if n.lower() not in taken)
    if not free:
        raise WorkflowError("No first name left in the catalog for a new employee", code=ErrorCode.NO_NAME_LEFT)
    return random.SystemRandom().choice(free)


def _catalog_channels_of(roles: list[str]) -> set[str]:
    return {c["name"] for c in load_catalog()["channels"] if "*" in c["roles"] or set(c["roles"]) & set(roles)}


async def add_member(
    s: AsyncSession, project: Project, *, name: str | None, roles: list[str], preset: str | None,
    model: str | None, account: int | None,
) -> Employee:  # fmt: skip
    """Hire a member: the name is drawn from the catalog unless given. They join the catalog
    channels of their roles; the team rules (a lead, permissions, size) must still hold."""
    roles = list(dict.fromkeys(roles))
    _check_roles(roles)
    _check_preset(preset)
    if len(project.employees) >= MAX_TEAM_SIZE:
        raise WorkflowError(f"A team has at most {MAX_TEAM_SIZE} members", code=ErrorCode.TEAM_TOO_LARGE)
    _check_team_rules([*(e.roles for e in project.employees), roles])
    member = custom_employee(roles, _free_name(project, name), preset=preset, model=model)
    employee = Employee(**asdict(member), account=account, mcp_token=secrets.token_urlsafe(32))
    project.employees.append(employee)
    await s.flush()
    wanted = _catalog_channels_of(roles)
    for room in project.rooms:
        if room.kind == services.DIRECTION or room.name not in wanted:
            continue
        room.members.append(employee)
    await projects._open_channels(s, project)  # A bigger team may now justify a channel it lacked
    await s.commit()
    return employee


async def change_member(
    s: AsyncSession, project: Project, employee: Employee, *, roles: list[str] | None,
    preset: str | None, model: str | None,
) -> None:  # fmt: skip
    """Change a member's roles and/or draw their personality from a preset. A new role set
    renews title, permissions and (unless `model` is given) model, keeps the personality, and
    moves the member between the catalog channels. The lead keeps their roles."""
    _check_preset(preset)
    if roles is not None:
        roles = list(dict.fromkeys(roles))
        _check_roles(roles)
        if MANDATORY_ROLE in employee.roles and roles != employee.roles:
            raise WorkflowError(f"The {MANDATORY_ROLE} cannot change roles", code=ErrorCode.LEAD_PROTECTED)
        _check_team_rules([roles if e is employee else e.roles for e in project.employees])
    if roles is not None and roles != employee.roles:
        _rebuild(employee, roles, model)
        _move_between_channels(project, employee, roles)
    if preset is not None:
        _apply_preset(employee, preset)
    await s.commit()


def _rebuild(employee: Employee, roles: list[str], model: str | None) -> None:
    fresh = custom_employee(
        roles, employee.name, traits=employee.traits, quirks=employee.quirks, style=employee.style, model=model
    )
    for field in ("roles", "title", "model", "permissions"):
        setattr(employee, field, getattr(fresh, field))


def _apply_preset(employee: Employee, preset: str) -> None:
    fresh = custom_employee(employee.roles, employee.name, preset=preset)
    for field in projects.PERSONALITY_FIELDS:
        setattr(employee, field, getattr(fresh, field))


def _move_between_channels(project: Project, employee: Employee, roles: list[str]) -> None:
    """Join the catalog channels of the new roles and leave those of the old ones; channels
    planned for this team (not in the catalog) are left alone."""
    catalog_names = {c["name"] for c in load_catalog()["channels"]}
    wanted = _catalog_channels_of(roles)
    for room in project.rooms:
        if room.kind == services.DIRECTION or room.name not in catalog_names:
            continue
        member = employee in room.members
        if room.name in wanted and not member:
            room.members.append(employee)
        elif room.name not in wanted and member:
            room.members.remove(employee)


async def remove_member(s: AsyncSession, project: Project, employee: Employee) -> None:
    """Let a member go: their unfinished tasks go back to todo, unassigned; they leave every
    room; their messages stay (signed by name). The lead cannot be removed."""
    if MANDATORY_ROLE in employee.roles:
        raise WorkflowError(f"The {MANDATORY_ROLE} cannot be removed", code=ErrorCode.LEAD_PROTECTED)
    if len(project.employees) <= MIN_TEAM_SIZE:
        raise WorkflowError(f"A team needs at least {MIN_TEAM_SIZE} members", code=ErrorCode.TEAM_TOO_SMALL)
    _check_team_rules([e.roles for e in project.employees if e is not employee])
    await s.execute(
        update(Task)
        .where(Task.assignee_id == employee.id, Task.status.not_in(CLOSED_STATUSES))
        .values(assignee_id=None, status=TaskStatus.todo)
    )
    for room in project.rooms:
        if employee in room.members:
            room.members.remove(employee)
    project.employees.remove(employee)  # delete-orphan
    await s.commit()
