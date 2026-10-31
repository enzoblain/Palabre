"""Project creation: the team is drawn at random from the catalog."""

import asyncio
import json
import logging
import random
import re
import secrets
import shutil
import tempfile
import tomllib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import github, release, services
from app.accounts import assign_accounts, token_for
from app.company import channel_planner
from app.company.team import Employee as TeamMember
from app.company.team import (
    RAPPORTEUR, Team, appoint_rapporteur, custom_employee, generate_team, kind_of_mode, load_catalog, personality_for,
    reroll_employee,
)  # fmt: skip
from app.models import (
    AgentRun, AppSetting, Conversation, Decision, DecisionStatus, Employee, Event, Message, OpenQuestion, Project, RequestAnswer, RequestStatus, Room, Task,
    TaskStatus,
)  # fmt: skip
from app.orchestrator.research import start_question
# NothingToRelease now lives in app.errors; kept importable from here for one release for external callers
from app.errors import ErrorCode, NothingToRelease, WorkflowError
from app import worktrees
from app.worktrees import sync_repo

log = logging.getLogger(__name__)

_background: set[asyncio.Task] = set()  # Strong references: the loop only keeps weak ones
RESEARCH_ROOM = "research"  # The one room of a research team (no generic channels elsewhere)
PERSONALITY_FIELDS = ("traits", "quirks", "style")


async def working_branch(repo_url: str) -> str:
    """The branch a new development project works on. The repository's default branch
    (production) is detected, never chosen: the team works on `dev` instead, created from
    it if missing, and only propose_release reaches production.
    An empty repository has no branch to create it from: `dev` is named anyway and its
    first commit (worktrees._initial_commit) creates production, then `dev`."""
    repo = github.repo_slug(repo_url)
    production = await github.resolve_branch(repo, "")
    if await github.has_commits(repo) and not await github.branch_exists(repo, github.WORKING_BRANCH):
        await github.create_branch(repo, github.WORKING_BRANCH, production)
    return github.WORKING_BRANCH


async def create_project(
    s: AsyncSession,
    *,
    name: str,
    repo_url: str,
    mode: str,
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
    default_branch = "main"  # model default; research has no repository
    if kind == "company":
        repo_url = github.https_url(repo_url)  # GitHub URLs only
        default_branch = await working_branch(repo_url)
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
    if kind == "research":
        # The research room holds everyone: the topic is posted there (see _kick_off_research)
        await _open_rooms(s, project, [(RESEARCH_ROOM, list(project.employees))])
    elif not employees:
        await _open_channels(s, project)  # A custom team gets its channels from plan_custom_channels
    await ensure_direction(s, project)
    await s.commit()
    if kind == "research" and topic:
        await _kick_off_research(s, project, topic)
    return project


async def _kick_off_research(s: AsyncSession, project: Project, topic: str) -> None:
    """The topic becomes the objective of the research room and the boss's first message,
    which starts the research (phase 1)."""
    room = next((r for r in project.rooms if r.name == RESEARCH_ROOM), None)
    if room is None:
        raise WorkflowError(f"The {RESEARCH_ROOM} room of project {project.id} is missing")
    room.objective = topic
    conversation_id = await s.scalar(select(Conversation.id).where(Conversation.room_id == room.id))
    message = await services.post_message(s, project.id, conversation_id, topic, None)
    start_question(s, project, conversation_id, message.id)
    await s.commit()


def _channel_members(channel: dict, employees: list[Employee]) -> list[Employee]:
    roles = set(channel["roles"])
    return [e for e in employees if "*" in roles or roles & set(e.roles)]


async def _open_channels(s: AsyncSession, project: Project) -> None:
    """Create the catalog's targeted channels the company is big enough for (each with a first
    conversation). Channels that already exist are left alone."""
    channels = load_catalog()["channels"]
    await _open_rooms(s, project, [(c["name"], _channel_members(c, project.employees)) for c in channels])


async def _open_rooms(s: AsyncSession, project: Project, rooms: list[tuple[str, list[Employee]]]) -> None:
    """Create the rooms with at least 2 members, a new name and a composition no room has yet."""
    existing = {room.name for room in project.rooms}
    groups = [{e.name for e in room.members} for room in project.rooms]
    for name, members in rooms:
        names = {e.name for e in members}
        if name in existing or len(members) < 2 or names in groups:
            continue
        room = Room(project=project, name=name, members=members)
        s.add(room)
        await s.flush()
        s.add(Conversation(room_id=room.id, title="Kickoff"))
        groups.append(names)
        existing.add(name)


def plan_custom_channels_later(project_id: int) -> None:
    """Plan the channels of a custom team in the background, never in the request."""
    task = asyncio.create_task(plan_custom_channels(project_id), name=f"channel-planner-{project_id}")
    _background.add(task)
    task.add_done_callback(_background.discard)


async def plan_custom_channels(project_id: int) -> None:
    """Open the channels a model proposes for a custom team; if anything fails, those of the catalog."""
    from app.db import SessionLocal  # Late: tests import this module without a database

    plan = None
    try:
        async with SessionLocal() as s:
            project = await load_project(s, project_id)
            lead = next((e for e in project.employees if "lead" in e.roles), None) if project else None
            if project is None or lead is None:
                return
            # Everything the call needs is read now: the rollback below expires the instances
            lead_id, lead_name = lead.id, lead.name
            members = [channel_planner.Member(name=e.name, roles=list(e.roles)) for e in project.employees]
            base = worktrees.project_dir(project)
            token = token_for(assign_accounts(project.employees)[lead_id])
            await s.rollback()  # No transaction open during the model call
        # An empty directory of its own: the lead's desk would load the repo's CLAUDE.md and hooks,
        # and the runner claims its cwd for the agent user, which would clash with the lead's runs
        base.mkdir(parents=True, exist_ok=True)
        cwd = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="channel-planner-", dir=base))
        try:
            plan = await channel_planner.plan_channels(
                members, lead_id=lead_id, lead_name=lead_name, token=token, cwd=cwd,
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, cwd, True)
    except Exception:
        log.exception("Cannot plan the channels of project %s, falling back to the catalog", project_id)
    try:
        async with SessionLocal() as s:
            project = await load_project(s, project_id)
            if project is None:
                return
            if plan is None:
                await _open_channels(s, project)
            else:
                by_name = {e.name: e for e in project.employees}
                await _open_rooms(s, project, [(c.name, [by_name[n] for n in c.members]) for c in plan])
            await s.commit()
    except Exception:
        log.exception("Cannot open the channels of project %s", project_id)


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


# Names of the channels every company used to get. A channel (kind "team") with one of them is
# generic unless the catalog targets that name. An AI plan or a user can name a channel the same
# later, so the migration runs once (marker below) and never sees those.
GENERIC_ROOMS_MARKER = "generic_rooms_dropped"
_GENERIC_ROOMS = {"general", "equipe", "couts-claude", "engineering", "product"}


def _is_generic_room(room: Room, targeted: set[str]) -> bool:
    return room.kind == "team" and room.name in _GENERIC_ROOMS and room.name not in targeted


async def drop_generic_rooms(s: AsyncSession) -> None:
    """There are no generic channels anymore: delete the old ones with their messages, and give
    the "general" room of a research project its new name. Their tasks, decisions and open
    questions move to the project's direction room first (they would cascade with the room).
    Direction, targeted channels and DMs are never touched. One-shot: a persistent marker stops
    later runs, so a #product created afterwards survives restarts."""
    if await s.get(AppSetting, GENERIC_ROOMS_MARKER) is not None:
        return
    targeted = {c["name"] for c in load_catalog()["channels"]}
    for project_id in list(await s.scalars(select(Project.id))):
        project = await load_project(s, project_id)
        if project.kind == "research":
            general = next((r for r in project.rooms if r.name == "general"), None)
            if general is not None and not any(r.name == RESEARCH_ROOM for r in project.rooms):
                general.name = RESEARCH_ROOM
            continue
        direction = next((r for r in project.rooms if r.kind == services.DIRECTION), None)
        direction_conversation = None
        if direction is not None:
            direction_conversation = await s.scalar(
                select(Conversation.id).where(Conversation.room_id == direction.id).order_by(Conversation.id).limit(1)
            )
        for room in project.rooms:
            if not _is_generic_room(room, targeted):
                continue
            if direction is not None and direction_conversation is not None:
                await s.execute(update(Task).where(Task.room_id == room.id).values(
                    room_id=direction.id, conversation_id=direction_conversation))
                await s.execute(update(Decision).where(Decision.room_id == room.id).values(room_id=direction.id))
                await s.execute(update(OpenQuestion).where(OpenQuestion.room_id == room.id).values(room_id=direction.id))
            else:
                # Nowhere to move them to: keep the room rather than lose them
                held = [Task.room_id, Decision.room_id, OpenQuestion.room_id]
                if any([await s.scalar(select(col).where(col == room.id).limit(1)) is not None for col in held]):
                    log.warning("Keeping generic room %r of project %s: it holds work and there is no direction room",
                                room.name, project_id)
                    continue
            conversations = select(Conversation.id).where(Conversation.room_id == room.id)
            # Keep the runs: they are the only record of tokens and cost (the FK would cascade them)
            await s.execute(update(AgentRun).where(AgentRun.conversation_id.in_(conversations)).values(conversation_id=None))
            await s.execute(delete(Message).where(Message.conversation_id.in_(conversations)))
            # Wakeups of these conversations cascade too: harmless, the dispatcher is not running yet
            await s.execute(delete(Conversation).where(Conversation.room_id == room.id))
            await s.delete(room)
    s.add(AppSetting(key=GENERIC_ROOMS_MARKER, value="1"))
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
            raise WorkflowError(f"traits must define {'only' if partial else 'exactly'} these axes: {', '.join(sorted(axes))}", code=ErrorCode.INVALID_PERSONALITY)
        if any(v not in personality["levels"] for v in traits.values()):
            raise WorkflowError(f"trait levels must be one of {personality['levels']}", code=ErrorCode.INVALID_PERSONALITY)
    if style is not None:
        keys = set(personality["style"])
        if (not set(style) <= keys) if partial else (set(style) != keys):
            raise WorkflowError(f"style must define {'only' if partial else 'exactly'}: {', '.join(sorted(keys))}", code=ErrorCode.INVALID_PERSONALITY)
        for key, value in style.items():
            if value not in personality["style"][key]:
                raise WorkflowError(f"style {key} must be one of: {', '.join(personality['style'][key])}", code=ErrorCode.INVALID_PERSONALITY)


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
                raise WorkflowError("No first name left in the catalog for a new employee", code=ErrorCode.NO_NAME_LEFT)
            member.name = free[0]
        taken.add(member.name)
        hired.append(Employee(**asdict(member), mcp_token=secrets.token_urlsafe(32)))

    channels = {c["name"]: c for c in load_catalog()["channels"]}
    for room in project.rooms:
        room.members = [m for m in room.members if m not in remaining]
        if room.kind == services.DIRECTION:
            continue
        # Newcomers join the research room (everyone) and the channels of their roles
        channel = channels.get(room.name)
        room.members.extend(
            e for e in hired if room.name == RESEARCH_ROOM or (channel and _channel_members(channel, [e]))
        )
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
        raise WorkflowError(f"Not a valid branch name: {branch}", code=ErrorCode.INVALID_BRANCH_NAME)
    if branch == project.default_branch:
        raise WorkflowError(f"The team already works on {branch}", code=ErrorCode.BRANCH_ALREADY_USED)
    repo = github.repo_slug(project.repo_url)
    if by is not None and branch == await github.resolve_branch(repo, ""):
        raise WorkflowError(
            f"{branch} is the production branch: only the boss can send the team's merges there",
            code=ErrorCode.PRODUCTION_BRANCH_BOSS_ONLY,
        )
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
            pr = await github.open_pull_request(repo, project.default_branch, production, f"chore(release): {title}", summary)
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


async def settle_release(project: Project, decision: Decision, accepted: bool, sha: str | None = None) -> None:
    """The boss's answer to a release: accepted, its PR is merged (a merge commit, so the
    team's branch and production keep the same history); rejected, it is closed."""
    repo = github.repo_slug(project.repo_url)
    if accepted:
        await github.merge_pull_request(
            repo, decision.pr_number, f"chore(release): {decision.title.removeprefix('Release: ')}", method="merge", sha=sha
        )
    else:
        try:
            await github.close_pull_request(repo, decision.pr_number)
        except github.GitHubError:
            pass  # Already closed or merged on GitHub


async def release_plan(project: Project) -> dict | None:
    """What the team's branch would publish: the next version (SemVer, from the Conventional Commits since
    the last vX.Y.Z tag), the previous one, the commits, the branch's tip and the number of commits
    production lacks. None when there is nothing worth a release."""
    repo = github.repo_slug(project.repo_url)
    production = await github.resolve_branch(repo, "")
    if project.default_branch == production:
        raise WorkflowError(f"The team already merges into {production}: there is nothing to release")
    tag = await github.latest_version_tag(repo)
    previous = tag.removeprefix("v") if tag else None
    _, commits = await github.compare_commits(repo, tag or production, project.default_branch)
    version = release.next_version(previous or "0.0.0", commits)
    if version is None:
        return None
    ahead, _ = await github.compare_commits(repo, production, project.default_branch)
    return {
        "version": version, "previous": previous, "commits": commits, "ahead": ahead,
        "tip": await github.branch_tip(repo, project.default_branch),
    }  # fmt: skip


async def prepare_release(project: Project) -> dict:
    """Commit the version bump and the CHANGELOG entry on the team's branch only (one commit,
    `chore(release): X.Y.Z`, made and pushed by the backend from its clone), computed from the
    commits since the last tag. Recomputed on every call (a commit merged after a previous bump still
    lands in the entry, and the version follows the bump level); nothing is committed when no file changes."""
    plan = await release_plan(project)
    if plan is None:
        raise NothingToRelease(f"Nothing worth a release on {project.default_branch}: no feat, fix, perf or breaking commit since the last tag")
    version, tip = plan["version"], plan["tip"]
    repo = github.repo_slug(project.repo_url)
    result = {"version": version, "previous": plan["previous"], "sha": tip["sha"], "committed": False, "changes": ""}
    texts = {path: await github.file_content(repo, path, tip["sha"]) for path in [*VERSION_FILES, "CHANGELOG.md"]}
    if all(texts[path] is None for path in VERSION_FILES):
        raise WorkflowError("No version file found in the repository: nothing to bump")
    package = _package_name(texts["frontend/src-tauri/Cargo.toml"])
    # Keep the date of an entry already written for this version, so a later day alone does not change it
    date = release.entry_date(texts["CHANGELOG.md"] or "", version) or datetime.now(UTC).date().isoformat()
    changes = result["changes"] = release.changelog_entry(version, date, plan["commits"])
    files = {}
    for path, text in texts.items():
        if text is None or path == "CHANGELOG.md":
            continue
        if (new := release.set_version(path, text, version, package)) != text:
            files[path] = new
    if texts["CHANGELOG.md"] is not None:
        try:
            updated = release.update_changelog(texts["CHANGELOG.md"], version, plan["previous"], changes)
        except ValueError as exc:
            raise WorkflowError(str(exc)) from exc
        if updated != texts["CHANGELOG.md"]:
            files["CHANGELOG.md"] = updated
    if not files:
        return result  # Already up to date: no empty commit
    for path in VERSION_FILES:  # A format we do not know must not ship a half-bumped version
        if texts[path] is not None and VERSION_FILES[path](files.get(path, texts[path]), package) not in (version, None):
            raise WorkflowError(f"{path} could not be bumped to {version}: its format is not the expected one")
    try:
        result["sha"] = await worktrees.commit_release(project, tip["sha"], files, f"chore(release): {version}")
    except github.GitHubError as exc:
        raise WorkflowError(f"The version bump could not be pushed to {project.default_branch}: {exc}") from exc
    result["committed"] = True
    return result


async def merge_release(s: AsyncSession, project: Project, title: str, summary: str) -> tuple[str, int]:
    """The lead merges the release PR (team's branch to production) without the boss's answer,
    under the same CI gate as a task. Opens the PR if there is none; a release the boss
    was asked about is settled as validated. Returns the PR's URL and number."""
    repo = github.repo_slug(project.repo_url)
    production = await github.resolve_branch(repo, "")
    if project.default_branch == production:
        raise WorkflowError(f"The team already merges into {production}: there is nothing to release")
    try:
        prepared = await prepare_release(project)  # No bump task: the version is computed here
    except NothingToRelease:
        prepared = None  # Only chores since the last tag: the lead merges as before
    title = title or (prepared["version"] if prepared else "")
    if not title:
        raise WorkflowError("A title is required when there is no version to publish")
    pr = await github.find_pull_request(repo, project.default_branch, production)
    if pr is None:
        try:
            pr = await github.open_pull_request(repo, project.default_branch, production, f"chore(release): {title}", summary)
        except github.GitHubError as exc:
            if "No commits between" in str(exc):
                raise WorkflowError(f"{project.default_branch} has nothing that {production} does not have yet") from None
            raise
    if prepared and prepared["committed"]:
        raise WorkflowError(
            f"Version {prepared['version']} was committed on {project.default_branch} and the release PR #{pr['number']} is open: "
            "its CI restarted, you will be woken up when it ends, then call merge_release again"
        )  # fmt: skip
    # CI is checked on this exact commit and the merge is pinned to it: a task merged into
    # the team's branch in between makes GitHub refuse instead of shipping unchecked code
    head_sha = pr["head"]["sha"]
    if ci := await github.commit_checks(repo, head_sha):
        raise WorkflowError(f"The release PR #{pr['number']} cannot be merged: {ci}")
    pending = await s.scalar(
        select(Decision).where(
            Decision.room_id.in_(select(Room.id).where(Room.project_id == project.id)),
            Decision.pr_number == pr["number"],
            Decision.status == DecisionStatus.proposed,
        )
    )
    if pending is not None:
        await settle_decision(
            s, pending, RequestAnswer.validated, "Merged by the lead, without the boss's answer",
            wake_proposer=False, merge_sha=head_sha,
        )  # fmt: skip
        await s.commit()
    else:
        await github.merge_pull_request(repo, pr["number"], f"chore(release): {title}", method="merge", sha=head_sha)
    project.main_ci_watch = True  # The scheduler tells the lead when CI on production ends
    await s.commit()
    return pr["html_url"], pr["number"]


SEMVER_RE = release.SEMVER_RE
def _lock_version(lock: dict) -> str:
    """The version of a package-lock.json: its two mentions must agree."""
    top, inner = lock.get("version"), lock.get("packages", {}).get("", {}).get("version", lock.get("version"))
    return str(top) if top == inner else f"{top} and {inner}"


def _package_name(cargo_toml: str | None) -> str:
    return tomllib.loads(cargo_toml).get("package", {}).get("name", "") if cargo_toml else ""


def _compose_version(text: str) -> str | None:
    """The image version a docker-compose.yml defaults to (`${PALABRE_VERSION:-X.Y.Z}`), None if it has none."""
    found = sorted(set(re.findall(r"\$\{PALABRE_VERSION:-([^}]*)\}", text)))
    return " and ".join(found) if found else None


# Where the app's version lives in the repository, and how to read it
VERSION_FILES = {
    "frontend/package.json": lambda text, _package: str(json.loads(text).get("version")),
    "frontend/package-lock.json": lambda text, _package: _lock_version(json.loads(text)),
    "frontend/src-tauri/tauri.conf.json": lambda text, _package: str(json.loads(text).get("version")),
    "frontend/src-tauri/Cargo.toml": lambda text, _package: str(tomllib.loads(text).get("package", {}).get("version")),
    "frontend/src-tauri/Cargo.lock": lambda text, package: str(
        next((p.get("version") for p in tomllib.loads(text).get("package", []) if p.get("name") == package), None)
    ),
    "docker-compose.yml": lambda text, _package: _compose_version(text),
}  # fmt: skip


async def publish_version(project: Project, version: str) -> str:
    """Tag the head of production with vX.Y.Z and publish the GitHub Release (the tag starts
    release.yml). Refused for a malformed version, an existing tag or files at another version."""
    version = version.strip().removeprefix("v")
    if not SEMVER_RE.match(version):
        raise WorkflowError(f"'{version}' is not a version: use X.Y.Z, e.g. 1.4.0")
    tag = f"v{version}"
    repo = github.repo_slug(project.repo_url)
    if await github.tag_exists(repo, tag):
        raise WorkflowError(f"The tag {tag} already exists")
    production = await github.resolve_branch(repo, "")
    sha = await github.branch_head(repo, production)
    # The tag publishes the images the team pulls: production's head must have passed CI
    if ci := await github.commit_checks(repo, sha):
        raise WorkflowError(f"{tag} cannot be published, {production} is not green: {ci}")
    mismatches = []
    package = ""
    for path, read in VERSION_FILES.items():
        text = await github.file_content(repo, path, sha)
        if text is None:
            continue  # A project without this file has no version to match
        if path.endswith("Cargo.toml"):
            package = _package_name(text)  # Before Cargo.lock, which needs it
        try:
            found = read(text, package)
        except ValueError:  # includes malformed JSON and TOML
            found = "unreadable"
        if found is not None and found != version:
            mismatches.append(f"{path} says {found}")
    if mismatches:
        raise WorkflowError(f"Version {version} does not match {production}: {'; '.join(mismatches)}")
    published = await github.create_release(repo, tag, sha)
    return published["html_url"]


async def fix_release(project: Project, version: str) -> str:
    """Reset the name and notes of an existing release to the standard ones."""
    version = version.strip().removeprefix("v")
    if not SEMVER_RE.match(version):
        raise WorkflowError(f"'{version}' is not a version: use X.Y.Z, e.g. 1.4.0")
    repo = github.repo_slug(project.repo_url)
    if not await github.tag_exists(repo, f"v{version}"):
        raise WorkflowError(f"The tag v{version} does not exist")
    try:
        published = await github.update_release(repo, f"v{version}")
    except github.GitHubError as exc:
        raise WorkflowError(f"v{version} has no release to fix: {exc}") from exc
    return published["html_url"]


async def open_pull_requests(s: AsyncSession, project: Project) -> list[dict]:
    """The repository's open PRs, each with the task it belongs to (None for an outside one,
    e.g. from Dependabot or a human)."""
    repo = github.repo_slug(project.repo_url)
    by_number = dict(
        (await s.execute(select(Task.pr_number, Task.id).where(Task.project_id == project.id, Task.pr_number.is_not(None)))).all()
    )
    return [
        {
            "number": pr["number"],
            "title": pr["title"],
            "author": pr["user"]["login"],
            "head": pr["head"]["ref"],
            "base": pr["base"]["ref"],
            "url": pr["html_url"],
            "task_id": by_number.get(pr["number"]),
        }
        for pr in await github.list_pull_requests(repo)
    ]


async def close_outside_pull_request(s: AsyncSession, project: Project, number: int, reason: str) -> dict:
    """Close a PR that no task owns (Dependabot, a human) with `reason` as a comment, and
    delete its branch when it lives in the repository. A task's PR goes through its task,
    the release PR through the boss; production and the team's branch are never deleted."""
    repo = github.repo_slug(project.repo_url)
    task_id = await s.scalar(select(Task.id).where(Task.project_id == project.id, Task.pr_number == number))
    if task_id is not None:
        raise WorkflowError(f"PR #{number} is task #{task_id}'s: cancel the task (update_task) instead")
    pr = await github.get_pull_request(repo, number)
    if pr["state"] != "open":
        raise WorkflowError(f"PR #{number} is already {'merged' if pr.get('merged') else 'closed'}")
    head = pr["head"]["ref"]
    production = await github.resolve_branch(repo, "")
    if head == project.default_branch:
        raise WorkflowError(f"PR #{number} is the release PR ({head} into {production}): only the boss rejects it")
    if not reason.strip():
        raise WorkflowError("Say why the PR is closed")
    await github.comment_pull_request(repo, number, reason.strip())
    await github.close_pull_request(repo, number)
    # A fork's branch is not ours; branches tasks or the team work on are left alone
    own = (pr["head"].get("repo") or {}).get("full_name", "").lower() == repo.lower()
    protected = {production, project.default_branch, github.WORKING_BRANCH}
    deleted = own and head not in protected and not github.is_task_branch_name(head)
    if deleted:
        await github.delete_branch(repo, head)
    return {"number": number, "url": pr["html_url"], "branch_deleted": head if deleted else None}


async def settle_decision(
    s: AsyncSession,
    decision: Decision,
    answer: RequestAnswer,
    comment: str = "",
    *,
    wake_proposer: bool = True,
    merge_sha: str | None = None,
) -> None:
    """Apply the boss's answer to a decision. A release is merged when validated and closed
    when rejected (GitHub refusing the merge raises and leaves everything as it was). A
    nuanced answer leaves a decision proposed; a nuanced release is dropped but its PR stays
    open, so the lead can reshape it and propose it again."""
    room = await s.get(Room, decision.room_id)
    is_release = decision.pr_number is not None and decision.status == DecisionStatus.proposed
    if is_release and answer != RequestAnswer.nuanced:
        project = await load_project(s, room.project_id)
        await settle_release(project, decision, answer == RequestAnswer.validated, merge_sha)
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


async def withdraw_request(s: AsyncSession, project_id: int, author: Employee, request_id: int, reason: str) -> Message:
    """The lead withdraws a pending request. The decision it asks about is rejected with the reason;
    a release request cannot be withdrawn (settle it, or let the boss answer)."""
    message = await services.withdraw_request(s, project_id, author, request_id, reason, commit=False)
    decision = None
    if message.request_decision_id is not None:
        decision = await s.get(Decision, message.request_decision_id)
    if message.request_kind == "release" or (decision is not None and decision.pr_number is not None):
        await s.rollback()
        raise WorkflowError(f"Request #{request_id} is about a release: it cannot be withdrawn")
    if decision is not None and decision.status == DecisionStatus.proposed:
        await s.flush()  # the request is withdrawn before the settling answers the other pending ones
        rejection = reason.strip()
        if message.request_author_id is not None:
            # Relayed for a member: the boss reads in direction that they did not answer
            rejection = f"Withdrawn by the lead, not answered by the boss: {rejection}"
        await settle_decision(s, decision, RequestAnswer.rejected, rejection, wake_proposer=False)
    await s.commit()
    return message


async def normalize_repo_urls(s: AsyncSession) -> None:
    """Projects created with an SSH URL (before they were converted at creation) get
    their HTTPS URL, which git can clone with the token."""
    for project in await s.scalars(select(Project).where(Project.repo_url.like("git@%"))):
        project.repo_url = github.https_url(project.repo_url)
    await s.commit()


RELAYED_ESCALATIONS_MARKER = "relayed_escalations_backfilled"


async def backfill_relayed_escalations(s: AsyncSession) -> None:
    """Pending escalations relayed before request_author_id existed carry the member's name as a
    "Name: " prefix: record who they are for, so the lead still cannot close them. One-shot: a
    persistent marker stops later runs, so the lead's own "Name: ..." escalations stay theirs."""
    if await s.get(AppSetting, RELAYED_ESCALATIONS_MARKER) is not None:
        return
    pending = await s.scalars(
        select(Message).where(
            Message.request_kind == "escalation",
            Message.request_status == RequestStatus.pending.value,
            Message.request_author_id.is_(None),
        )
    )
    for message in pending:
        signer = await s.get(Employee, message.employee_id) if message.employee_id is not None else None
        if signer is None or "lead" not in signer.roles:
            continue
        members = await s.scalars(select(Employee).where(Employee.project_id == signer.project_id, Employee.id != signer.id))
        for member in sorted(members, key=lambda e: len(e.name), reverse=True):
            if message.content.startswith(f"{member.name}: "):
                message.request_author_id = member.id
                break
    s.add(AppSetting(key=RELAYED_ESCALATIONS_MARKER, value="1"))
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
