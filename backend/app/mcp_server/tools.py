"""MCP tools. Each one is only visible to the positions listed in permissions.py."""

from typing import Literal

from mcp.server.mcpserver import Context

from app import projects, services, toolchains, web_fetch, workflow
from app.db import SessionLocal
from app.errors import WorkflowError
from app.mcp_server.server import current_caller, tool
from app.models import Employee, Project

# --- Conversation (everyone) -------------------------------------------------------


@tool
async def read_messages(ctx: Context, since_id: int | None = None, limit: int = 50) -> list[dict]:
    """Read messages of the current conversation, in chronological order.

    since_id: only return messages with a greater id (to read what is new).
    Without since_id, returns the last `limit` messages.
    """
    c = current_caller(ctx)
    async with SessionLocal() as s:
        messages = await services.get_messages(s, c.conversation_id, since_id, max(1, min(limit, 200)))
    return [
        {
            "id": m.id,
            "author": m.author_name,
            "is_me": m.employee_id == c.employee_id,
            "is_boss": m.employee_id is None and not m.is_system,
            "is_system": m.is_system,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


async def _check_chat(s, project_id: int, content: str) -> None:
    project = await s.get(Project, project_id)
    services.check_chat_message(content, project.kind)


@tool
async def send_message(ctx: Context, content: str, channel: str | None = None) -> dict:
    """Post a message in the current conversation, signed with your name: a short chat
    message, like you would send a colleague (a long or report-like one is refused).
    Mention colleagues with @Name to get their attention.
    channel: a channel you are a member of, or "@Name" for a direct message (the other
    person is woken up without an @; a DM has two members, so an @ to anyone else in it is refused).
    Only the lead may post in "direction"."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, content)
        me = await s.get(Employee, c.employee_id)
        conversation_id = c.conversation_id
        if channel is not None:
            if "create_channel" in c.tools:  # held by the lead only
                if channel.strip().startswith("@"):
                    conversation_id = await services.get_or_create_dm(s, c.project_id, me, channel)
                else:
                    conversation_id = await services.channel_conversation_id(s, c.project_id, channel)
            else:
                conversation_id = await services.member_conversation_id(s, c.project_id, me, channel)
        msg = await services.post_message(s, c.project_id, conversation_id, content, me)
    return {"id": msg.id}


@tool
async def create_channel(ctx: Context, name: str, members: list[str]) -> dict:
    """Create a team channel (e.g. "backend", "front", "quality") with the given members,
    by first name. You are always in it. The boss does not see it."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        room = await services.create_channel(s, c.project_id, name, members)
    return {"id": room.id, "name": room.name}


@tool
async def ask_ceo(ctx: Context, content: str, kind: Literal["decision", "question", "escalation"] = "question") -> dict:
    """Ask the boss something in the direction channel. They answer with Validate, Reject or
    Nuance (a free comment), and you are woken up with their answer. Use it when you need
    their go or arbitration; a plain update is a send_message with channel="direction".
    content: what you ask, short and self-contained, with your recommendation."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, content)
        me = await s.get(Employee, c.employee_id)
        msg = await services.ask_boss(s, c.project_id, me, content, kind)
    if msg is None:
        raise WorkflowError("This project has no direction channel to ask the boss in")
    return {"message_id": msg.id, "status": "waiting for the boss"}


@tool
async def list_pending_requests(ctx: Context) -> list[dict]:
    """Your requests to the boss (ask_ceo, decisions, releases...) that still wait for an
    answer, oldest first: id, content, kind and date. Use it to tidy up with withdraw_request
    and merge_requests."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        me = await s.get(Employee, c.employee_id)
        found = await services.list_pending_requests(s, c.project_id, me)
    return [{"id": m.id, "kind": m.request_kind, "content": m.content, "created_at": m.created_at.isoformat()} for m in found]


@tool
async def withdraw_request(ctx: Context, request_id: int, reason: str) -> dict:
    """Withdraw one of your pending requests to the boss that became useless (obsolete, done
    another way). It leaves their open requests and they can no longer answer it. A request
    already answered is refused, and so is a release request. If it asks about a decision, the
    decision is rejected with your reason. reason: why, in a sentence."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, reason)
        me = await s.get(Employee, c.employee_id)
        msg = await projects.withdraw_request(s, c.project_id, me, request_id, reason)
    return {"id": msg.id, "status": msg.request_status}


@tool
async def merge_requests(ctx: Context, request_ids: list[int], content: str) -> dict:
    """Replace several of your pending requests to the boss (duplicates, same topic) by a single
    new one with the given content. The old ones are marked merged and point to it. A request
    already answered, or about a decision or a release, is refused. content: the new request, short and self-contained, with your recommendation."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, content)
        me = await s.get(Employee, c.employee_id)
        msg = await services.merge_requests(s, c.project_id, me, request_ids, content)
    return {"message_id": msg.id, "merged": request_ids, "status": "waiting for the boss"}


@tool
async def get_room_context(ctx: Context) -> dict:
    """The room's shared document: objective, members, decisions (proposed / validated /
    rejected), open questions, who does what, and summary."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        return await services.room_context(s, c.room_id)


@tool
async def list_tasks(
    ctx: Context,
    status: Literal["todo", "in_progress", "review", "changes_requested", "done", "cancelled"]
    | None = None,
    mine: bool = False,
) -> list[dict]:
    """List the project's tasks, optionally filtered by status or to your own tasks."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        return await workflow.list_tasks(s, c.project_id, status, c.employee_id if mine else None)


@tool
async def get_task(ctx: Context, task_id: int) -> dict:
    """Full details of a task: description, acceptance criteria, PR, reviews."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        return await workflow.task_detail(s, c.project_id, task_id)


@tool
async def add_question(ctx: Context, question: str) -> dict:
    """Add an open question to the room document."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        me = await s.get(Employee, c.employee_id)
        q = await services.add_question(s, c.room_id, question, me)
    return {"id": q.id}


@tool
async def escalate(ctx: Context, reason: str, to: Literal["lead", "boss"] = "lead") -> dict:
    """Escalate a blocker or disagreement you cannot resolve at your level. With to="boss" the
    request reaches the boss through the lead's name: keep it short, in the team's language.
    `reason` is posted in the conversation as a message to them: write it as you would say it."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, reason)
        me = await s.get(Employee, c.employee_id)
        msg = await services.escalate(s, c.project_id, c.conversation_id, me, to, reason)
    return {"message_id": msg.id}


@tool
async def read_notes(ctx: Context) -> str:
    """Read your personal notebook (kept across sessions, private to you)."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        return await services.read_notes(s, c.employee_id)


@tool
async def write_notes(ctx: Context, content: str, append: bool = True) -> str:
    """Write to your personal notebook. append=False replaces its whole content."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        return await services.write_notes(s, c.employee_id, content, append)


# --- Decisions ---------------------------------------------------------------------


@tool
async def add_decision(ctx: Context, title: str, rationale: str = "") -> dict:
    """Propose a decision in the room document. It stays "proposed" until the boss
    validates or rejects it. title: the decision in one short sentence; rationale: the why in
    a few sentences (the boss only sees a truncated version, the detail belongs in the room
    document). Write both in the team's language. The boss's request is signed by the lead."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        me = await s.get(Employee, c.employee_id)
        decision = await services.add_decision(s, c.project_id, c.room_id, title, rationale, me)
    return {"id": decision.id, "status": decision.status.value}


# --- Task management ---------------------------------------------------------------


@tool
async def create_task(
    ctx: Context,
    title: str,
    description: str,
    acceptance_criteria: list[str],
    assignee: str | None = None,
    depends_on: list[int] | None = None,
) -> dict:
    """Create a task in the current room. assignee: an employee's first name."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        me = await s.get(Employee, c.employee_id)
        room_id, conversation_id = await services.team_context(s, c.project_id, c.room_id, c.conversation_id)
        task = await workflow.create_task(
            s,
            project_id=c.project_id,
            room_id=room_id,
            conversation_id=conversation_id,
            author=me,
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria,
            assignee=assignee,
            depends_on=depends_on or [],
        )
        return workflow.task_summary(task)


@tool
async def assign_task(ctx: Context, task_id: int, assignee: str) -> dict:
    """Assign (or reassign) a task to an employee, by first name."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        return workflow.task_summary(await workflow.assign_task(s, c.project_id, task_id, assignee))


@tool
async def update_task(
    ctx: Context,
    task_id: int,
    title: str | None = None,
    description: str | None = None,
    acceptance_criteria: list[str] | None = None,
    depends_on: list[int] | None = None,
    status: Literal["todo", "cancelled"] | None = None,
) -> dict:
    """Edit a task. Status can only be reset to todo or cancelled; the rest follows the workflow."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        task = await workflow.update_task(
            s,
            c.project_id,
            task_id,
            author=await s.get(Employee, c.employee_id),
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria,
            depends_on=depends_on,
            status=status,
        )
        return await workflow.task_detail(s, c.project_id, task.id)


@tool
async def start_task(ctx: Context, task_id: int) -> str:
    """Go work on your task: you are woken up again in a moment in the task's own
    worktree, where you can code, commit and submit_for_review. Call it from a
    conversation when it is time to work on your task (you were unblocked, someone
    asked you to start), then stop: never code a task from a conversation."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        me = await s.get(Employee, c.employee_id)
        task = await workflow.start_task(s, c.project_id, task_id, me)
    return f"You will be woken up on task #{task.id} in its worktree in a moment. Stop here."


# --- Task run (assignee only) ------------------------------------------------------


@tool
async def report_progress(ctx: Context, message: str) -> dict:
    """Tell the team how your task is going, in a short chat message."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        msg = await services.post_message(s, c.project_id, c.conversation_id, message, me)
    return {"id": msg.id}


@tool
async def submit_for_review(ctx: Context, title: str, summary: str, message: str, sensitive: bool = False) -> dict:
    """Submit your current task for review: your branch is pushed and a pull request is
    opened (or updated). Commit your work first.
    title: the pull request title and squash commit title, in English, Conventional Commits
    format `type(scope): description`, for example `feat(usage): show real Claude usage per model`
    (the PR number is added for you; refused if the format is not respected).
    summary: the pull request description, in English (as detailed as needed). It is the whole PR body:
    the task's own text is not copied, so cover what changed and why.
    message: what you tell the team in the chat, in a sentence or two (the PR link is added).
    sensitive: true if the change touches auth, personal data, dependencies or secrets."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        task = await workflow.submit_for_review(s, c.project_id, c.task_id, me, summary, sensitive, message, title)
        return workflow.task_summary(task)


# --- Review ------------------------------------------------------------------------


@tool
async def get_diff(ctx: Context, task_id: int) -> str:
    """The diff of a task's branch against the default branch."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        return await workflow.get_diff(s, c.project_id, task_id)


@tool
async def review_task(
    ctx: Context,
    task_id: int,
    verdict: Literal["approve", "changes", "comment"],
    body: str,
    head_sha: str,
) -> dict:
    """Review a task waiting for review. Reference files and lines in the body
    (e.g. `src/app.py:42 — ...`). The body is posted on the GitHub PR: write it in English.
    head_sha: the `Head:` commit shown by get_diff (required); the review is refused if the PR moved since.
    Returns what still blocks the merge."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        me = await s.get(Employee, c.employee_id)
        blockers = await workflow.review_task(s, c.project_id, task_id, me, verdict, body, head_sha)
    return {"task_id": task_id, "verdict": verdict, "merge_blockers": blockers}


@tool
async def report_bug(
    ctx: Context,
    title: str,
    steps: str,
    expected: str,
    actual: str,
    severity: Literal["low", "medium", "high", "critical"] = "medium",
    related_task_id: int | None = None,
) -> dict:
    """File a bug ticket. The lead triages and assigns it."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        me = await s.get(Employee, c.employee_id)
        room_id, conversation_id = await services.team_context(s, c.project_id, c.room_id, c.conversation_id)
        task = await workflow.report_bug(
            s,
            project_id=c.project_id,
            room_id=room_id,
            conversation_id=conversation_id,
            author=me,
            title=title,
            steps=steps,
            expected=expected,
            actual=actual,
            severity=severity,
            related_task_id=related_task_id,
        )
    return {"task_id": task.id}


# --- Room document (scribe) --------------------------------------------------------


@tool
async def update_summary(ctx: Context, summary: str) -> dict:
    """Replace the room's summary with a short project summary, not a recap of the conversation.

    Cover what the project is, its goal, where it stands and what was delivered, in the team's language.
    Research rooms are the exception: there the summary is the final research report."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await services.update_summary(s, c.room_id, summary)
    return {"ok": True}


@tool
async def resolve_question(ctx: Context, question_id: int, answer: str) -> dict:
    """Mark an open question as resolved, with its answer."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await services.resolve_question(s, c.room_id, question_id, answer)
    return {"ok": True}


# --- Merge (lead) ------------------------------------------------------------------


@tool
async def merge_task(ctx: Context, task_id: int, message: str) -> dict:
    """Merge a task's pull request (always a squash merge: one commit on the team's
    branch). Refused, with the reasons, until every rule of the company's mode is met
    (approvals, QA, security, CI, changelog).
    message: what you tell the team in the chat, in a sentence or two (the PR link is added)."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        return workflow.task_summary(await workflow.merge_task(s, c.project_id, task_id, me, message=message))


@tool
async def set_working_branch(ctx: Context, branch: str, message: str) -> dict:
    """Move the team to another branch, e.g. "dev": new tasks start from it and every PR
    merges into it. A branch missing on GitHub is created from the current one, and the
    open PRs are retargeted to it. The repository's default branch (production) is
    refused: only the boss merges into it, or sends the team back there.
    message: what you tell the team in the chat, in a sentence or two."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        project = await projects.change_branch(s, await projects.load_project(s, c.project_id), branch.strip(), by=me)
        await services.post_message(s, c.project_id, c.conversation_id, f"{message.strip()} (branch: `{branch.strip()}`)", me)
    return {"branch": project.default_branch}


@tool
async def list_pull_requests(ctx: Context) -> list[dict]:
    """The repository's open pull requests. task_id is null for one no task owns
    (Dependabot, a human): those you can close with close_pull_request."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        return await projects.open_pull_requests(s, await projects.load_project(s, c.project_id))


@tool
async def close_pull_request(ctx: Context, number: int, reason: str, message: str) -> dict:
    """Close a pull request no task owns (e.g. Dependabot) and delete its branch. A task's
    PR is closed by cancelling the task; the release PR is the boss's to reject.
    reason: posted as a comment on the PR, in English, e.g. "Not needed: we stay on v4".
    message: what you tell the team in the chat, in a sentence or two (the PR link is added)."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        project = await projects.load_project(s, c.project_id)
        result = await projects.close_outside_pull_request(s, project, number, reason)
        await services.post_message(s, c.project_id, c.conversation_id, f"{message.strip()} ({result['url']})", me)
    return result


@tool
async def propose_release(ctx: Context, title: str, summary: str, message: str) -> dict:
    """When the team's branch (e.g. "dev") holds a step worth shipping, open the pull
    request from it to production (the repository's default branch) and ask the boss to
    accept it: a request in direction that merges it when they validate it. One release at a time.
    title: what ships, in English (it goes to GitHub), e.g. "Checkout and order history".
    summary: the PR description (it goes to GitHub, in English), in Markdown: what changes for users, what was tested, known limits.
    message: what you tell the team in the chat, in a sentence or two."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        project = await projects.load_project(s, c.project_id)
        decision = await projects.propose_release(s, project, c.room_id, title.strip(), summary.strip(), me)
        text = f"{message.strip()} ({decision.pr_url})"
        if await services.ask_boss(s, c.project_id, me, text, "release", decision.id) is None:
            await services.post_message(s, c.project_id, c.conversation_id, text, me)
    return {"decision_id": decision.id, "pr_url": decision.pr_url, "status": "waiting for the boss"}


@tool
async def merge_release(ctx: Context, summary: str, message: str, title: str = "") -> dict:
    """Merge the release pull request (the team's branch into production) yourself, without
    waiting for the boss's Validate. Refused until CI is green on the PR's head (call it again
    once the checks of a freshly opened PR are done), and the merge fails if the head moved
    meanwhile. The version bump is made for you first (no bump task): the next SemVer version and the CHANGELOG entry are
    committed on the team's branch; the PR is then opened, its CI restarts and you are woken up when it ends, then call
    merge_release again. The PR is opened if missing. The boss is told in direction, with nothing to answer. To get their
    opinion first, use propose_release.
    title: optional, what ships in English (it goes to GitHub); the version by default, e.g. "0.7.0".
    summary: the PR description (it goes to GitHub, in English), in Markdown: what changes for users, what was tested, known limits.
    message: what you tell the team in the chat, in a sentence or two."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        project = await projects.load_project(s, c.project_id)
        pr_url, number = await projects.merge_release(s, project, title.strip(), summary.strip())
        text = f"{message.strip()} (release merged: {pr_url})"
        direction = await services.direction_conversation_id(s, c.project_id)
        await services.post_message(s, c.project_id, direction or c.conversation_id, text, me)
        if direction and direction != c.conversation_id:
            await services.post_message(s, c.project_id, c.conversation_id, text, me)
    return {"merged": True, "pr_number": number, "pr_url": pr_url}


@tool
async def publish_version(ctx: Context, version: str, message: str) -> dict:
    """Tag the head of production (the default branch) vX.Y.Z and publish the GitHub Release
    (named "Palabre vX.Y.Z", with the standard download notes); the tag builds the images and the desktop app. Refused for a version that
    is not X.Y.Z, a tag that already exists, or a version that differs from the one in the
    repository's files (frontend/package.json, tauri.conf.json, Cargo.toml: the ones that exist),
    or when CI is not green on production's head. Merge a version bump first.
    version: e.g. "1.4.0".
    message: what you tell the team in the chat, in a sentence or two."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        project = await projects.load_project(s, c.project_id)
        url = await projects.publish_version(project, version)
        await services.post_message(s, c.project_id, c.conversation_id, f"{message.strip()} ({url})", me)
    return {"version": version.strip().removeprefix("v"), "release_url": url}


@tool
async def fix_release(ctx: Context, version: str, message: str) -> dict:
    """Reset the name and notes of an existing GitHub Release to the standard ones
    ("Palabre vX.Y.Z" and the download notes), e.g. after a release published with other text.
    version: e.g. "0.2.3".
    message: what you tell the team in the chat, in a sentence or two."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        project = await projects.load_project(s, c.project_id)
        url = await projects.fix_release(project, version)
        await services.post_message(s, c.project_id, c.conversation_id, f"{message.strip()} ({url})", me)
    return {"version": version.strip().removeprefix("v"), "release_url": url}


# --- Toolchains (lead, devops) -------------------------------------------------------


@tool
async def install_toolchain(
    ctx: Context, name: Literal["node", "go", "python"], version: str = "", packages: str = ""
) -> str:
    """Install a toolchain for the whole team: every agent's commands can use it right
    away, and it stays installed. Installing another version switches the team to it.
    - node: Node.js with npm and npx. version: "lts" (default), "latest", "20", "20.11.1"
    - go: version "stable" (default), "1.22", "1.22.3"
    - python: a shared venv (python, pip) that survives redeployments. Agents cannot pip
      install into it: list the PyPI packages in `packages`, e.g. "pytest pytest-asyncio==0.23.0"
      (call again to add more). Wheels only, no version argument.
    System packages (apt) cannot be installed this way: ask the boss for those."""
    current_caller(ctx)
    result = await toolchains.install(name, version, packages)
    commands = ", ".join(sorted(toolchains.installed()))
    return f"{result}\nInstalled commands: {commands}"


# --- Research groups -----------------------------------------------------------------


@tool
async def fetch_page(ctx: Context, url: str) -> str:
    """Read a web page: GET over https only, run by the backend (your sandbox has no
    network). Returns the page's text, cut to a size limit. Pages on private or local
    addresses are refused."""
    current_caller(ctx)
    return await web_fetch.fetch_page(url)
