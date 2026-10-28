"""MCP tools. Each one is only visible to the positions listed in permissions.py."""

from typing import Literal

from mcp.server.mcpserver import Context

from app import services, toolchains, workflow
from app.db import SessionLocal
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
            "is_boss": m.employee_id is None,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


async def _check_chat(s, project_id: int, content: str) -> None:
    project = await s.get(Project, project_id)
    services.check_chat_message(content, project.kind)


@tool
async def send_message(ctx: Context, content: str) -> dict:
    """Post a message in the current conversation, signed with your name: a short chat
    message, like you would send a colleague (a long or report-like one is refused).
    Mention colleagues with @Name (or @boss) to get their attention."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, content)
        me = await s.get(Employee, c.employee_id)
        msg = await services.post_message(s, c.project_id, c.conversation_id, content, me)
    return {"id": msg.id}


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
    """Escalate a blocker or disagreement you cannot resolve at your level.
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
    validates or rejects it."""
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
        task = await workflow.create_task(
            s,
            project_id=c.project_id,
            room_id=c.room_id,
            conversation_id=c.conversation_id,
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
async def submit_for_review(ctx: Context, summary: str, message: str, sensitive: bool = False) -> dict:
    """Submit your current task for review: your branch is pushed and a pull request is
    opened (or updated). Commit your work first.
    summary: the pull request description (as detailed as needed).
    message: what you tell the team in the chat, in a sentence or two (the PR link is added).
    sensitive: true if the change touches auth, personal data, dependencies or secrets."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        task = await workflow.submit_for_review(s, c.project_id, c.task_id, me, summary, sensitive, message)
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
    ctx: Context, task_id: int, verdict: Literal["approve", "changes", "comment"], body: str
) -> dict:
    """Review a task waiting for review. Reference files and lines in the body
    (e.g. `src/app.py:42 — ...`). Returns what still blocks the merge."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        me = await s.get(Employee, c.employee_id)
        blockers = await workflow.review_task(s, c.project_id, task_id, me, verdict, body)
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
        task = await workflow.report_bug(
            s,
            project_id=c.project_id,
            room_id=c.room_id,
            conversation_id=c.conversation_id,
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
    """Replace the room's summary."""
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
    """Merge a task's pull request (always a squash merge: one commit on the default
    branch). Refused, with the reasons, until every rule of the company's mode is met
    (approvals, QA, security, CI, changelog).
    message: what you tell the team in the chat, in a sentence or two (the PR link is added)."""
    c = current_caller(ctx)
    async with SessionLocal() as s:
        await _check_chat(s, c.project_id, message)
        me = await s.get(Employee, c.employee_id)
        return workflow.task_summary(await workflow.merge_task(s, c.project_id, task_id, me, message=message))


# --- Toolchains (lead, devops) -------------------------------------------------------


@tool
async def install_toolchain(ctx: Context, name: Literal["node", "go"], version: str = "") -> str:
    """Install a toolchain for the whole team: every agent's commands can use it right
    away, and it stays installed. Installing another version switches the team to it.
    - node: Node.js with npm and npx. version: "lts" (default), "latest", "20", "20.11.1"
    - go: version "stable" (default), "1.22", "1.22.3"
    System packages (apt) cannot be installed this way: ask the boss for those."""
    current_caller(ctx)
    result = await toolchains.install(name, version)
    commands = ", ".join(sorted(toolchains.installed()))
    return f"{result}\nInstalled commands: {commands}"
