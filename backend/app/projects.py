"""Project creation: the team is drawn at random from the catalog."""

import secrets
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import github
from app.company.team import Employee as TeamMember
from app.company.team import Team, generate_team, load_catalog, reroll_employee
from app.models import Conversation, Employee, Project, Room
from app.services import WorkflowError

PERSONALITY_FIELDS = ("traits", "quirks", "style")


async def create_project(
    s: AsyncSession,
    *,
    name: str,
    repo_url: str,
    mode: str,
    default_branch: str = "main",
    seed: int | None = None,
) -> Project:
    github.repo_slug(repo_url)  # GitHub URLs only
    team = generate_team(mode, seed)
    project = Project(
        name=name, repo_url=repo_url, default_branch=default_branch, mode=team.mode, seed=team.seed
    )
    project.employees = [
        Employee(**asdict(member), mcp_token=secrets.token_urlsafe(32)) for member in team.employees
    ]
    room = Room(project=project, name="general", members=list(project.employees))
    s.add_all([project, room])
    await s.flush()
    s.add(Conversation(room_id=room.id, title="Kickoff"))
    await s.commit()
    return project


def team_of(project: Project) -> Team:
    """Rebuild the catalog Team (for render_system_prompt) from a stored project."""
    fields = TeamMember.__dataclass_fields__
    return Team(
        mode=project.mode,
        seed=project.seed,
        process=dict(load_catalog()["modes"][project.mode]["process"]),
        employees=[TeamMember(**{f: getattr(e, f) for f in fields}) for e in project.employees],
    )


async def load_project(s: AsyncSession, project_id: int) -> Project | None:
    return await s.scalar(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.employees), selectinload(Project.rooms).selectinload(Room.members))
        .execution_options(populate_existing=True)
    )


async def reroll_personality(s: AsyncSession, employee: Employee) -> Employee:
    """Draw a new personality for one employee (name and roles are kept)."""
    project = await load_project(s, employee.project_id)
    team = team_of(project)
    index = next(i for i, m in enumerate(team.employees) if m.name == employee.name)
    member = reroll_employee(team, index)
    for field in PERSONALITY_FIELDS:
        setattr(employee, field, getattr(member, field))
    await s.commit()
    return employee


def validate_personality(traits: dict[str, int] | None, style: dict[str, str] | None) -> None:
    personality = load_catalog()["personality"]
    if traits is not None:
        axes = {a["key"] for a in personality["axes"]}
        if set(traits) != axes:
            raise WorkflowError(f"traits must define exactly these axes: {', '.join(sorted(axes))}")
        if any(v not in personality["levels"] for v in traits.values()):
            raise WorkflowError(f"trait levels must be one of {personality['levels']}")
    if style is not None and set(style) != set(personality["style"]):
        raise WorkflowError(f"style must define exactly: {', '.join(personality['style'])}")


async def change_mode(s: AsyncSession, project: Project, mode: str) -> Project:
    """Grow or shrink the company: keep the employees whose seat still exists in the new
    mode, hire new ones for the new seats, and let go of those whose seat disappears."""
    new_team = generate_team(mode, project.seed)
    names = set(load_catalog()["people"]["names"])
    remaining = list(project.employees)
    taken = {e.name for e in remaining}
    kept: list[Employee] = []
    hired: list[Employee] = []
    for member in new_team.employees:
        match = next((e for e in remaining if e.roles == member.roles), None)
        if match is not None:
            remaining.remove(match)
            kept.append(match)
            continue
        if member.name in taken:
            free = sorted(names - taken)
            if not free:
                raise WorkflowError("No first name left in the catalog for a new employee")
            member.name = free[0]
        taken.add(member.name)
        hired.append(Employee(**asdict(member), mcp_token=secrets.token_urlsafe(32)))

    for room in project.rooms:
        room.members = [m for m in room.members if m not in remaining]
    if project.rooms:
        project.rooms[0].members.extend(hired)  # Newcomers join the general room
    project.employees = kept + hired  # Those left in `remaining` are deleted (orphans)
    project.mode = mode
    await s.commit()
    return await load_project(s, project.id)
