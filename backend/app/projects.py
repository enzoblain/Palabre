"""Project creation: the team is drawn at random from the catalog."""

import secrets
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from app import github
from app.company.team import Employee as TeamMember
from app.company.team import Team, generate_team, load_catalog
from app.models import Conversation, Employee, Project, Room


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
