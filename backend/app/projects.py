"""Project creation: the team is drawn at random from the catalog."""

import random
import re
import secrets
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import github, services
from app.company.team import Employee as TeamMember
from app.company.team import (
    RAPPORTEUR, Team, appoint_rapporteur, custom_employee, generate_team, kind_of_mode, load_catalog, personality_for,
    reroll_employee,
)  # fmt: skip
from app.models import (
    Conversation, Decision, DecisionStatus, Employee, Event, Message, Project, RequestAnswer, Room, Task, TaskStatus,
)  # fmt: skip
from app.orchestrator.research import start_question
from app.services import WorkflowError
from app.worktrees import sync_repo

PERSONALITY_FIELDS = ("traits", "quirks", "style")


async def working_branch(repo_url: str, branch: str) -> str:
    """The branch a new development project works on. `branch` is the one resolved at
    creation: when it is the repository's default branch (production), the team works on
    `dev` instead, created from it if missing, and only propose_release reaches production.
    An empty repository has no branch to create it from: `dev` is named anyway and its
    first commit (worktrees._initial_commit) creates production, then `dev`."""
    repo = github.repo_slug(repo_url)
    if branch != await github.resolve_branch(repo, ""):
        return branch
    if await github.has_commits(repo) and not await github.branch_exists(repo, github.WORKING_BRANCH):
        await github.create_branch(repo, github.WORKING_BRANCH, branch)
    return github.WORKING_BRANCH


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
        repo_url = github.https_url(repo_url)  # GitHub URLs only
        default_branch = await working_branch(repo_url, default_branch)
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
    await ensure_direction(s, project)
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


async def ensure_direction(s: AsyncSession, project: Project) -> None:
    """A company has a "direction" channel: the boss and the lead, nobody else. It is
    created after the team channels, so the first room stays the team's."""
    lead = next((e for e in project.employees if "lead" in e.roles), None)
    if project.kind != "company" or lead is None:
        return
    existing = next((r for r in project.rooms if r.kind == services.DIRECTION), None)
    if existing is not None:
        existing.members = [lead]  # A new lead (change of company size) takes the seat
        return
    room = Room(project=project, name=services.DIRECTION, kind=services.DIRECTION, members=[lead])
    s.add(room)
    await s.flush()
    s.add(Conversation(room_id=room.id, title="Direction"))


async def ensure_all_directions(s: AsyncSession) -> None:
    """Existing companies get their direction channel (their rooms stay team channels)."""
    for project_id in list(await s.scalars(select(Project.id).where(Project.kind == "company"))):
        await ensure_direction(s, await load_project(s, project_id))
    await s.commit()


async def migrate_inbox(s: AsyncSession) -> None:
    """The inbox is gone: what waited in it becomes requests in direction, then its
    notifications (events for the boss) are purged. Safe to run at every startup."""
    escalations = await s.scalars(
        select(Event).where(Event.target_role == "boss", Event.type == "escalation", Event.processed_at.is_(None))
    )
    for event in escalations:
        message = await s.get(Message, event.payload.get("message_id"))
        if message is not None and message.request_kind is None:
            message.request_kind, message.request_status = "escalation", "pending"
    pending = await s.scalars(select(Decision).where(Decision.status == DecisionStatus.proposed))
    for decision in pending:
        asked = await s.scalar(select(Message.id).where(Message.request_decision_id == decision.id).limit(1))
        room = await s.get(Room, decision.room_id)
        if asked is not None or room is None:
            continue
        employees = list(await s.scalars(select(Employee).where(Employee.project_id == room.project_id)))
        author = next(
            (e for e in employees if e.name == decision.proposed_by), next((e for e in employees if "lead" in e.roles), None)
        )
        if author is None:
            continue
        kind = "release" if decision.pr_number is not None else "decision"
        text = f"{'Release' if kind == 'release' else 'Decision'} to validate: {decision.title}"
        if decision.pr_url:
            text += f" ({decision.pr_url})"
        await services.ask_boss(s, room.project_id, author, text, kind, decision.id)
    await s.execute(delete(Event).where(Event.target_role == "boss"))
    await s.commit()


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
        if room.kind == services.DIRECTION:
            continue
        # Newcomers join the general room and the channels of their roles
        channel = channels.get(room.name)
        room.members.extend(e for e in hired if i == 0 or (channel and _channel_members(channel, [e])))
    project.employees = kept + hired  # Those left in `remaining` are deleted (orphans)
    if project.kind == "research":
        appoint_rapporteur(project.employees)  # The one who left was perhaps the rapporteur
    project.mode = mode
    await _open_channels(s, project)  # A bigger company gets the channels it lacked
    await ensure_direction(s, project)
    await s.commit()
    return await load_project(s, project.id)


async def change_branch(s: AsyncSession, project: Project, branch: str, by: Employee | None = None) -> Project:
    """Point the team at another branch: tasks start from it and their PRs merge into it
    (e.g. a `dev` branch, merged into `main` by the boss). A branch missing on GitHub is
    created from the current one; the open PRs are retargeted to it.
    by: the lead doing it. They cannot pick the repository's default branch (production):
    only the boss sends the team's merges there."""
    if not re.match(github.BRANCH_PATTERN, branch):
        raise WorkflowError(f"Not a valid branch name: {branch}")
    if branch == project.default_branch:
        raise WorkflowError(f"The team already works on {branch}")
    repo = github.repo_slug(project.repo_url)
    if by is not None and branch == await github.resolve_branch(repo, ""):
        raise WorkflowError(f"{branch} is the production branch: only the boss can send the team's merges there")
    if not await github.branch_exists(repo, branch):
        await github.create_branch(repo, branch, project.default_branch)
    open_prs = await s.scalars(
        select(Task).where(
            Task.project_id == project.id,
            Task.pr_number.is_not(None),
            Task.status.not_in([TaskStatus.done, TaskStatus.cancelled]),
        )
    )
    for task in open_prs:
        await github.set_pull_request_base(repo, task.pr_number, branch)
    project.default_branch = branch
    await s.commit()
    await sync_repo(project)
    return await load_project(s, project.id)


async def propose_release(s: AsyncSession, project: Project, room_id: int, title: str, summary: str, by: Employee) -> Decision:
    """Open the PR from the team's branch to production (the repository's default branch)
    and ask the boss to accept it: a decision that merges the PR once validated."""
    repo = github.repo_slug(project.repo_url)
    production = await github.resolve_branch(repo, "")
    if project.default_branch == production:
        raise WorkflowError(f"The team already merges into {production}: there is nothing to release")
    pending = await s.scalar(
        select(Decision).where(
            Decision.room_id.in_(select(Room.id).where(Room.project_id == project.id)),
            Decision.pr_number.is_not(None),
            Decision.status == DecisionStatus.proposed,
        )
    )
    if pending is not None:
        raise WorkflowError(f"A release is already waiting for the boss: {pending.title} ({pending.pr_url})")
    pr = await github.find_pull_request(repo, project.default_branch, production)
    if pr is None:
        try:
            pr = await github.open_pull_request(repo, project.default_branch, production, title, summary)
        except github.GitHubError as exc:
            if "No commits between" in str(exc):
                raise WorkflowError(f"{project.default_branch} has nothing that {production} does not have yet") from None
            raise
    decision = Decision(
        room_id=room_id, title=f"Release: {title}", proposed_by=by.name, pr_number=pr["number"], pr_url=pr["html_url"],
        rationale=f"Merge `{project.default_branch}` into `{production}`: [PR #{pr['number']}]({pr['html_url']})\n\n{summary}",
    )  # fmt: skip
    s.add(decision)
    await s.flush()
    await s.commit()
    return decision


async def settle_release(project: Project, decision: Decision, accepted: bool) -> None:
    """The boss's answer to a release: accepted, its PR is merged (a merge commit, so the
    team's branch and production keep the same history); rejected, it is closed."""
    repo = github.repo_slug(project.repo_url)
    if accepted:
        await github.merge_pull_request(repo, decision.pr_number, decision.title, method="merge")
    else:
        try:
            await github.close_pull_request(repo, decision.pr_number)
        except github.GitHubError:
            pass  # Already closed or merged on GitHub


async def settle_decision(
    s: AsyncSession, decision: Decision, answer: RequestAnswer, comment: str = "", *, wake_proposer: bool = True
) -> None:
    """Apply the boss's answer to a decision. A release is merged when validated and closed
    when rejected (GitHub refusing the merge raises and leaves everything as it was). A
    nuanced answer leaves a decision proposed; a nuanced release is dropped but its PR stays
    open, so the lead can reshape it and propose it again."""
    room = await s.get(Room, decision.room_id)
    is_release = decision.pr_number is not None and decision.status == DecisionStatus.proposed
    if is_release and answer != RequestAnswer.nuanced:
        await settle_release(await load_project(s, room.project_id), decision, answer == RequestAnswer.validated)
    if answer == RequestAnswer.nuanced:
        status = DecisionStatus.rejected if is_release else DecisionStatus.proposed
    else:
        status = DecisionStatus(answer.value)
    now = datetime.now(UTC)
    if status != DecisionStatus.proposed:
        decision.status, decision.decided_at = status, now
    payload = {"decision_id": decision.id, "status": answer.value, "room_id": room.id}
    services.emit_event(s, room.project_id, "decision_changed", payload)
    if wake_proposer:
        proposer = await s.scalar(
            select(Employee).where(Employee.project_id == room.project_id, Employee.name == decision.proposed_by)
        )
        if proposer is not None:
            services.emit_event(s, room.project_id, "decision_changed", payload, employee_id=proposer.id)
    # The requests asking the boss about this decision are answered
    await s.execute(
        update(Message)
        .where(Message.request_decision_id == decision.id, Message.request_status == "pending")
        .values(request_status=answer.value, request_comment=comment or None, request_answered_at=now)
    )


async def answer_request(s: AsyncSession, message_id: int, answer: RequestAnswer, comment: str = "") -> Message:
    """The boss answers a request of the lead, once. The answer is stored on the message and
    wakes the lead up with it; a request about a decision or a release settles it too."""
    message = await s.get(Message, message_id, with_for_update=True)  # two clicks: one answer
    if message is None or message.request_kind is None:
        raise WorkflowError(f"Message #{message_id} does not ask anything")
    if message.request_status != "pending":
        raise WorkflowError(f"Message #{message_id} was already answered ({message.request_status})")
    conversation = await s.get(Conversation, message.conversation_id)
    room = await s.get(Room, conversation.room_id)
    comment = comment.strip()
    employees = await s.scalars(select(Employee).where(Employee.project_id == room.project_id))
    lead = next((e for e in employees if "lead" in e.roles), None)
    if message.request_decision_id is not None:
        decision = await s.get(Decision, message.request_decision_id)
        if decision is not None:
            # The lead is woken by the answer itself: no second wakeup for their own proposal
            await settle_decision(s, decision, answer, comment, wake_proposer=lead is None or decision.proposed_by != lead.name)
    message.request_status = answer.value
    message.request_comment = comment or None
    message.request_answered_at = datetime.now(UTC)
    if lead is not None:
        payload = {
            "conversation_id": message.conversation_id, "message_id": message.id,
            "answer": answer.value, "comment": comment or "(no comment)", "request": message.request_kind,
            "asked_by": message.author_name,
        }  # fmt: skip
        services.emit_event(s, room.project_id, "ceo_answer", payload, employee_id=lead.id)
    await s.commit()
    return message


async def normalize_repo_urls(s: AsyncSession) -> None:
    """Projects created with an SSH URL (before they were converted at creation) get
    their HTTPS URL, which git can clone with the token."""
    for project in await s.scalars(select(Project).where(Project.repo_url.like("git@%"))):
        project.repo_url = github.https_url(project.repo_url)
    await s.commit()


async def refresh_permissions(s: AsyncSession) -> None:
    """Permissions come from the roles: recompute them for every employee, so a change
    in the catalog applies to existing teams too."""
    roles = load_catalog()["roles"]
    for employee in await s.scalars(select(Employee)):
        permissions = sorted({p for r in employee.roles if r in roles for p in roles[r]["permissions"]})
        if permissions != employee.permissions:
            employee.permissions = permissions
    await s.commit()
