"""Project creation: the team is drawn at random from the catalog."""

import random
import secrets
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import github, services
from app.company.team import Employee as TeamMember
from app.company.team import (
    RAPPORTEUR, Team, appoint_rapporteur, custom_employee, generate_team, kind_of_mode, load_catalog, personality_for,
    reroll_employee,
)  # fmt: skip
from app.models import Conversation, Employee, Project, Room
from app.orchestrator.research import start_question
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
    accounts: dict[str, int] | None = None,
    employees: list[dict] | None = None,
    topic: str | None = None,
    rapporteur: str | None = None,
    kind: str | None = None,
) -> Project:
    """`employees`: a team built by hand (see MemberIn); otherwise it is drawn for the mode.
    A research project (research mode) has a `topic` and no repository, and a `rapporteur`
    (a peer's name; none: drawn at random, unless the team built by hand has one)."""
    kind = kind_of_mode(mode)
    if kind == "company":
        github.repo_slug(repo_url)  # GitHub URLs only
    else:
        repo_url = ""
    if employees:
        seed = random.SystemRandom().randrange(2**32) if seed is None else seed
        accounts = {**(accounts or {}), **{m["name"]: m["account"] for m in employees if m.get("account")}}
        members = [
            custom_employee(
                m["roles"], m["name"], traits=m.get("traits"), quirks=m.get("quirks"), style=m.get("style"),
                model=m.get("model"), seed=seed + i, kind=kind,
            )  # fmt: skip
            for i, m in enumerate(employees)
        ]
        team = Team(mode=mode, seed=seed, process=dict(load_catalog()["modes"][mode]["process"]), employees=members)
    else:
        team = generate_team(mode, seed)
    if kind == "research":
        try:
            appoint_rapporteur(team.employees, rapporteur)
        except ValueError as exc:
            raise WorkflowError(str(exc)) from None
    project = Project(
        name=name, repo_url=repo_url, default_branch=default_branch, mode=team.mode, seed=team.seed,
        kind=kind, topic=topic if kind == "research" else None,
    )
    project.employees = [
        Employee(**asdict(member), account=(accounts or {}).get(member.name), mcp_token=secrets.token_urlsafe(32))
        for member in team.employees
    ]
    s.add(project)
    await _open_channels(s, project)
    await s.commit()
    if kind == "research" and topic:
        await _kick_off_research(s, project, topic)
    return project


async def _kick_off_research(s: AsyncSession, project: Project, topic: str) -> None:
    """The topic becomes the objective of the general room and the boss's first message,
    which starts the research (phase 1)."""
    room = project.rooms[0]
    room.objective = topic
    conversation_id = await s.scalar(select(Conversation.id).where(Conversation.room_id == room.id))
    message = await services.post_message(s, project.id, conversation_id, topic, None)
    start_question(s, project, conversation_id, message.id)
    await s.commit()


def _channel_members(channel: dict, employees: list[Employee]) -> list[Employee]:
    roles = set(channel["roles"])
    return [e for e in employees if "*" in roles or roles & set(e.roles)]


async def _open_channels(s: AsyncSession, project: Project) -> None:
    """Create the catalog's channels the company is big enough for (each with a first
    conversation). Channels that already exist are left alone."""
    existing = {room.name for room in project.rooms}
    groups = [{e.name for e in room.members} for room in project.rooms]
    for channel in load_catalog()["channels"]:
        members = _channel_members(channel, project.employees)
        names = {e.name for e in members}
        if channel["name"] in existing or len(members) < 2 or names in groups:
            continue
        room = Room(project=project, name=channel["name"], members=members)
        s.add(room)
        await s.flush()
        s.add(Conversation(room_id=room.id, title="Kickoff"))
        groups.append(names)


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


def validate_personality(
    traits: dict[str, int] | None, style: dict[str, str] | None, partial: bool = False, kind: str = "company"
) -> None:
    """partial: some axes or style keys may be left out (they are drawn at random)."""
    personality = personality_for(kind)
    if traits is not None:
        axes = {a["key"] for a in personality["axes"]}
        if (not set(traits) <= axes) if partial else (set(traits) != axes):
            raise WorkflowError(f"traits must define {'only' if partial else 'exactly'} these axes: {', '.join(sorted(axes))}")
        if any(v not in personality["levels"] for v in traits.values()):
            raise WorkflowError(f"trait levels must be one of {personality['levels']}")
    if style is not None:
        keys = set(personality["style"])
        if (not set(style) <= keys) if partial else (set(style) != keys):
            raise WorkflowError(f"style must define {'only' if partial else 'exactly'}: {', '.join(sorted(keys))}")
        for key, value in style.items():
            if value not in personality["style"][key]:
                raise WorkflowError(f"style {key} must be one of: {', '.join(personality['style'][key])}")


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
        # The rapporteur is not a seat: they keep their own angle's seat
        match = next((e for e in remaining if [r for r in e.roles if r != RAPPORTEUR] == member.roles), None)
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

    channels = {c["name"]: c for c in load_catalog()["channels"]}
    for i, room in enumerate(project.rooms):
        room.members = [m for m in room.members if m not in remaining]
        # Newcomers join the general room and the channels of their roles
        channel = channels.get(room.name)
        room.members.extend(e for e in hired if i == 0 or (channel and _channel_members(channel, [e])))
    project.employees = kept + hired  # Those left in `remaining` are deleted (orphans)
    if project.kind == "research":
        appoint_rapporteur(project.employees)  # The one who left was perhaps the rapporteur
    project.mode = mode
    await _open_channels(s, project)  # A bigger company gets the channels it lacked
    await s.commit()
    return await load_project(s, project.id)


async def refresh_permissions(s: AsyncSession) -> None:
    """Permissions come from the roles: recompute them for every employee, so a change
    in the catalog applies to existing teams too."""
    roles = load_catalog()["roles"]
    for employee in await s.scalars(select(Employee)):
        permissions = sorted({p for r in employee.roles if r in roles for p in roles[r]["permissions"]})
        if permissions != employee.permissions:
            employee.permissions = permissions
    await s.commit()
