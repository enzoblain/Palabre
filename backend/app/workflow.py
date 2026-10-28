"""Task lifecycle: creation, assignment, review and merge, with the mode's merge gates."""

import logging
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import github
from app.config import settings
from app.company.team import load_catalog
from app.models import Employee, Project, Review, Task, TaskKind, TaskStatus, Verdict
from app.services import WorkflowError, emit_event, post_message, post_system_message
from app.worktrees import final_branch_name, remove_task_worktree, rename_branch, repo_dir

MAX_DIFF_CHARS = 100_000
EDITABLE_STATUSES = {TaskStatus.todo, TaskStatus.cancelled}

log = logging.getLogger(__name__)


async def announce(s: AsyncSession, task: Task, text: str) -> None:
    """One short line about a step of the task, in its conversation, with the link."""
    await post_system_message(s, task.conversation_id, f"{text} · #{task.id} {task.title} {task.pr_url or ''}".strip())


_VERDICT_LABELS = {
    Verdict.approve: "approved",
    Verdict.changes: "requested changes",
    Verdict.comment: "commented",
}


def mode_process(mode: str) -> dict:
    return load_catalog()["modes"][mode]["process"]


async def get_task(s: AsyncSession, project_id: int, task_id: int) -> Task:
    task = await s.scalar(
        select(Task).where(Task.id == task_id).options(selectinload(Task.assignee))
    )
    if task is None or task.project_id != project_id:
        raise WorkflowError(f"Task #{task_id} does not exist in this project")
    return task


async def find_employee(s: AsyncSession, project_id: int, name: str) -> Employee:
    employee = await s.scalar(
        select(Employee).where(Employee.project_id == project_id, Employee.name.ilike(name.strip()))
    )
    if employee is None:
        raise WorkflowError(f"No employee named {name!r} in this company")
    return employee


def task_summary(task: Task) -> dict:
    return {
        "id": task.id,
        "kind": task.kind.value,
        "title": task.title,
        "status": task.status.value,
        "assignee": task.assignee.name if task.assignee else None,
        "depends_on": task.depends_on,
        "pr_url": task.pr_url,
    }


# --- Tasks -------------------------------------------------------------------------


async def list_tasks(
    s: AsyncSession, project_id: int, status: str | None = None, assignee_id: int | None = None
) -> list[dict]:
    q = select(Task).where(Task.project_id == project_id).options(selectinload(Task.assignee))
    if status:
        q = q.where(Task.status == TaskStatus(status))
    if assignee_id is not None:
        q = q.where(Task.assignee_id == assignee_id)
    return [task_summary(t) for t in await s.scalars(q.order_by(Task.id))]


async def task_detail(s: AsyncSession, project_id: int, task_id: int) -> dict:
    task = await get_task(s, project_id, task_id)
    reviews = await s.scalars(
        select(Review).where(Review.task_id == task.id).options(selectinload(Review.reviewer)).order_by(Review.id)
    )
    return {
        **task_summary(task),
        "description": task.description,
        "acceptance_criteria": task.acceptance_criteria,
        "severity": task.severity,
        "sensitive": task.sensitive,
        "branch": task.branch,
        "reviews": [
            {"reviewer": r.reviewer.name, "verdict": r.verdict.value, "body": r.body, "at": r.created_at.isoformat()}
            for r in reviews
        ],
    }


async def _check_dependencies(s: AsyncSession, project_id: int, depends_on: list[int]) -> None:
    for dep_id in depends_on:
        await get_task(s, project_id, dep_id)


async def create_task(
    s: AsyncSession,
    *,
    project_id: int,
    room_id: int,
    conversation_id: int,
    author: Employee | None,
    title: str,
    description: str,
    acceptance_criteria: list[str],
    assignee: str | None,
    depends_on: list[int],
) -> Task:
    await _check_dependencies(s, project_id, depends_on)
    task = Task(
        project_id=project_id,
        room_id=room_id,
        conversation_id=conversation_id,
        title=title,
        description=description,
        acceptance_criteria=acceptance_criteria,
        depends_on=depends_on,
        created_by_id=author.id if author else None,
    )
    if assignee:
        task.assignee_id = (await find_employee(s, project_id, assignee)).id
    s.add(task)
    await s.flush()
    if task.assignee_id:
        emit_event(s, project_id, "task_assigned", {"task_id": task.id}, employee_id=task.assignee_id)
    await s.commit()
    return await get_task(s, project_id, task.id)


async def assign_task(s: AsyncSession, project_id: int, task_id: int, assignee: str) -> Task:
    task = await get_task(s, project_id, task_id)
    if task.status not in {TaskStatus.todo, TaskStatus.in_progress, TaskStatus.changes_requested}:
        raise WorkflowError(f"Task #{task_id} is {task.status.value} and can no longer be reassigned")
    employee = await find_employee(s, project_id, assignee)
    task.assignee_id = employee.id
    emit_event(s, project_id, "task_assigned", {"task_id": task.id}, employee_id=employee.id)
    await s.commit()
    return await get_task(s, project_id, task_id)


async def update_task(
    s: AsyncSession,
    project_id: int,
    task_id: int,
    *,
    title: str | None,
    description: str | None,
    acceptance_criteria: list[str] | None,
    depends_on: list[int] | None,
    status: str | None,
) -> Task:
    task = await get_task(s, project_id, task_id)
    if title is not None:
        task.title = title
    if description is not None:
        task.description = description
    if acceptance_criteria is not None:
        task.acceptance_criteria = acceptance_criteria
    if depends_on is not None:
        await _check_dependencies(s, project_id, depends_on)
        task.depends_on = depends_on
    if status is not None:
        new_status = TaskStatus(status)
        if new_status not in EDITABLE_STATUSES:
            raise WorkflowError("Status can only be set to 'todo' or 'cancelled'; the rest follows the workflow")
        was_cancelled = task.status == TaskStatus.cancelled
        task.status = new_status
        if new_status == TaskStatus.cancelled and not was_cancelled:
            await clean_up_task(await s.get(Project, project_id), task)
    await s.commit()
    return task


async def report_bug(
    s: AsyncSession,
    *,
    project_id: int,
    room_id: int,
    conversation_id: int,
    author: Employee,
    title: str,
    steps: str,
    expected: str,
    actual: str,
    severity: str,
    related_task_id: int | None,
) -> Task:
    if related_task_id is not None:
        await get_task(s, project_id, related_task_id)
    description = f"Steps to reproduce:\n{steps}\n\nExpected:\n{expected}\n\nActual:\n{actual}"
    if related_task_id is not None:
        description += f"\n\nRelated task: #{related_task_id}"
    task = Task(
        project_id=project_id,
        room_id=room_id,
        conversation_id=conversation_id,
        kind=TaskKind.bug,
        title=title,
        description=description,
        severity=severity,
        created_by_id=author.id,
    )
    s.add(task)
    await s.flush()
    emit_event(s, project_id, "bug_reported", {"task_id": task.id, "severity": severity}, role="lead")
    await s.commit()
    return task


# --- Review ------------------------------------------------------------------------


async def _commits_ahead(project: Project, task: Task) -> int:
    base = f"origin/{project.default_branch}"
    return int((await github.git(task.worktree_path, "rev-list", "--count", f"{base}..HEAD")).strip())


async def start_task(s: AsyncSession, project_id: int, task_id: int, employee: Employee) -> Task:
    """Wake the assignee up on their task (from a conversation): the work itself only
    happens in a task run, in the task's worktree."""
    task = await get_task(s, project_id, task_id)
    if task.assignee_id != employee.id:
        raise WorkflowError(f"Task #{task.id} is not assigned to you")
    if task.status not in {TaskStatus.todo, TaskStatus.in_progress, TaskStatus.changes_requested}:
        raise WorkflowError(f"Task #{task.id} is {task.status.value}: there is nothing to work on")
    if task.depends_on:
        statuses = await s.scalars(select(Task.status).where(Task.id.in_(task.depends_on)))
        if any(st != TaskStatus.done for st in statuses):
            raise WorkflowError(f"Task #{task.id} is still waiting for tasks {task.depends_on}")
    emit_event(s, project_id, "task_resume", {"task_id": task.id}, employee_id=employee.id)
    await s.commit()
    return task


CONVENTIONAL_TITLE = re.compile(
    r"(feat|fix|chore|docs|refactor|test|ci|perf|build|style|revert)(\([a-z0-9][a-z0-9._/-]*\))?!?: [^\s(].*"
)
_TASK_REF = re.compile(r"\s*\(#\d+\)$")


def conventional_title(title: str, pr_number: int | None = None) -> str:
    """The English Conventional Commits title of a task's PR and squash commit, with the PR
    number last once the PR exists: `feat(usage): show real usage (#60)`. The task number never goes
    there: on GitHub `#N` is a PR. Raises WorkflowError if it does not follow the format."""
    title = _TASK_REF.sub("", title.strip())
    if len(title) > 100 or not CONVENTIONAL_TITLE.fullmatch(title) or not title.isascii():
        raise WorkflowError(
            f"Invalid title {title!r}: use an English Conventional Commits title of at most 100 ASCII characters, "
            "`type(scope): description` with type among feat, fix, chore, docs, refactor, test, ci, perf, build, "
            "style, revert; for example `feat(usage): show real Claude usage per model`. "
            "The PR number is added for you."
        )
    return title if pr_number is None else f"{title} (#{pr_number})"


async def submit_for_review(
    s: AsyncSession, project_id: int, task_id: int, author: Employee, summary: str, sensitive: bool,
    message: str = "", title: str = "",
) -> Task:
    """summary: the pull request description; message: what the author tells the team;
    title: the PR and squash commit title, in English Conventional Commits format."""
    project = await s.get(Project, project_id)
    task = await get_task(s, project_id, task_id)
    if task.assignee_id != author.id:
        raise WorkflowError("Only the assignee can submit this task for review")
    if task.status not in {TaskStatus.in_progress, TaskStatus.changes_requested}:
        raise WorkflowError(f"Task #{task.id} is {task.status.value}, it cannot be submitted")
    if not task.branch or not task.worktree_path:
        raise WorkflowError("This task has no branch yet")
    bare_title = conventional_title(title)
    if task.pr_number is None and github.is_task_branch_name(task.branch):
        # First submission: the branch gets its standard `<type>/<id>-<slug>` name before any push
        await rename_branch(task, final_branch_name(bare_title, task.id))
    if await _commits_ahead(project, task) == 0:
        raise WorkflowError("No commits on your branch: commit your work before submitting")

    repo = github.repo_slug(project.repo_url)
    # The task branch belongs to its assignee alone: a rebased branch is force-pushed,
    # unless someone else pushed to it in the meantime (lease)
    await github.git(
        task.worktree_path, "push", "--force-with-lease", "--set-upstream", "origin", task.branch,
        repo_url=project.repo_url,
    )  # fmt: skip
    if task.pr_number is None:
        criteria = "\n".join(f"- [ ] {c}" for c in task.acceptance_criteria) or "_None_"
        pr = await github.open_pull_request(
            repo,
            head=task.branch,
            base=project.default_branch,
            title=bare_title,
            body=(
                f"{task.description}\n\n**Acceptance criteria**\n{criteria}\n\n"
                f"**Summary from {author.name}**\n{summary}\n\n_Palabre task #{task.id}_"
            ),
        )
        task.pr_number, task.pr_url = pr["number"], pr["html_url"]
        # The PR number is only known now: it goes last in the title, which becomes the squash commit's
        task.pr_title = conventional_title(bare_title, task.pr_number)
        await github.set_pull_request_title(repo, task.pr_number, task.pr_title)
    else:
        task.pr_title = conventional_title(bare_title, task.pr_number)
        await github.set_pull_request_title(repo, task.pr_number, task.pr_title)
        await github.comment_pull_request(repo, task.pr_number, f"**Updated by {author.name}**\n\n{summary}")

    task.status = TaskStatus.review
    task.submitted_at = datetime.now(UTC)
    task.review_round += 1
    task.merge_ready_at = task.lead_reminded_at = None
    task.sensitive = task.sensitive or sensitive
    process = mode_process(project.mode)
    payload = {"task_id": task.id, "pr_url": task.pr_url}
    emit_event(s, project_id, "review_requested", payload, role="reviewer")
    if process["qa_gate"]:
        emit_event(s, project_id, "pr_ready", payload, role="qa")
    if process["security_gate"] and task.sensitive:
        emit_event(s, project_id, "sensitive_pr", payload, role="security")
    await announce(s, task, f"PR submitted by {author.name} (round {task.review_round})")
    # In the author's own words, with the link
    await post_message(s, project_id, task.conversation_id, f"{message.strip()} {task.pr_url}".strip(), author)
    return task


async def get_diff(s: AsyncSession, project_id: int, task_id: int) -> str:
    project = await s.get(Project, project_id)
    task = await get_task(s, project_id, task_id)
    if not task.branch:
        raise WorkflowError(f"Task #{task.id} has no branch yet")
    repo = repo_dir(project)
    try:
        await github.git(repo, "fetch", "--quiet", "origin", project.default_branch, repo_url=project.repo_url)
    except github.GitHubError:
        pass  # Diff against the last fetched state
    base = f"origin/{project.default_branch}...{task.branch}"
    stat = await github.git(repo, "diff", "--stat", base)
    diff = await github.git(repo, "diff", base)
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[diff truncated: read the files directly for the rest]"
    return f"{stat}\n{diff}"


async def review_task(
    s: AsyncSession, project_id: int, task_id: int, reviewer: Employee, verdict: str, body: str
) -> list[str]:
    """Record a review. Returns what still blocks the merge."""
    project = await s.get(Project, project_id)
    task = await get_task(s, project_id, task_id)
    if task.status != TaskStatus.review:
        raise WorkflowError(f"Task #{task.id} is {task.status.value}, not waiting for review")
    if task.assignee_id == reviewer.id:
        raise WorkflowError("You cannot review your own task")

    review = Review(
        task_id=task.id, reviewer_id=reviewer.id, verdict=Verdict(verdict), body=body, round=task.review_round
    )
    s.add(review)
    await s.flush()
    if task.pr_number is not None:
        await github.post_review(
            github.repo_slug(project.repo_url), task.pr_number,
            f"**{reviewer.name} ({reviewer.title}) — {verdict}**\n\n{body}",
        )  # fmt: skip

    await announce(s, task, f"{reviewer.name} ({reviewer.title}): {_VERDICT_LABELS[review.verdict]}")
    payload = {"task_id": task.id, "reviewer": reviewer.name}
    if review.verdict == Verdict.changes:
        task.status = TaskStatus.changes_requested
        emit_event(s, project_id, "changes_requested", payload, employee_id=task.assignee_id)
    await s.commit()

    blockers = await merge_blockers(s, project, task) if task.status == TaskStatus.review else []
    if review.verdict == Verdict.approve and not blockers:
        await mark_merge_ready(s, task, reviewer.name)
        await s.commit()
    return blockers


async def mark_merge_ready(s: AsyncSession, task: Task, by: str) -> None:
    """Every merge rule is met (the caller checked merge_blockers): wake up the lead, once."""
    if task.merge_ready_at is not None:
        return
    task.merge_ready_at = datetime.now(UTC)
    emit_event(s, task.project_id, "pr_approved", {"task_id": task.id, "reviewer": by}, role="lead")


async def remind_merge(s: AsyncSession, task: Task) -> None:
    """The task has been mergeable for too long: remind the lead, once."""
    task.lead_reminded_at = datetime.now(UTC)
    by = f"the team and has met every merge rule for {settings.merge_reminder_minutes} minutes (reminder)"
    emit_event(s, task.project_id, "pr_approved", {"task_id": task.id, "reviewer": by}, role="lead")


async def merge_blockers(s: AsyncSession, project: Project, task: Task) -> list[str]:
    """Everything that prevents merging this task under the company's mode."""
    process = mode_process(project.mode)
    reviews = await s.scalars(
        select(Review)
        .where(Review.task_id == task.id, Review.round == task.review_round)
        .options(selectinload(Review.reviewer))
        .order_by(Review.id)
    )
    # Latest approve/changes verdict of each reviewer since the last submission
    latest: dict[int, Review] = {}
    for r in reviews:
        if r.verdict != Verdict.comment:
            latest[r.reviewer_id] = r
    approvers = [r.reviewer for r in latest.values() if r.verdict == Verdict.approve]

    blockers = [
        f"{r.reviewer.name} requested changes" for r in latest.values() if r.verdict == Verdict.changes
    ]
    reviewer_approvals = sum("reviewer" in e.roles for e in approvers)
    if reviewer_approvals < process["required_approvals"]:
        blockers.append(f"{reviewer_approvals}/{process['required_approvals']} reviewer approval(s)")
    if process["qa_gate"] and not any("qa" in e.roles for e in approvers):
        blockers.append("QA has not approved")
    if process["security_gate"] and task.sensitive and not any("security" in e.roles for e in approvers):
        blockers.append("security has not approved this sensitive PR")
    if process["ci_required"] and task.pr_number is not None:
        if ci := await github.checks_status(github.repo_slug(project.repo_url), task.pr_number):
            blockers.append(ci)
    if process["docs_required"]:
        files = (
            await github.git(repo_dir(project), "diff", "--name-only", f"origin/{project.default_branch}...{task.branch}")
        ).split()
        if not any(PurePosixPath(f).name.upper().startswith("CHANGELOG") for f in files):
            blockers.append("the changelog was not updated")
    return blockers


def is_task_branch(project: Project, branch: str | None) -> bool:
    """Only a task's own branch may be deleted: never the default branch, `dev` or a release."""
    return github.is_task_branch_name(branch) and branch not in {project.default_branch, github.WORKING_BRANCH}


async def clean_up_task(project: Project, task: Task) -> None:
    """A finished task leaves nothing behind: its PR is closed if still open, its branch is
    deleted on GitHub and locally, and its worktree removed. Idempotent; a GitHub or git
    error is logged and never blocks the caller (the status change is already done)."""
    repo = github.repo_slug(project.repo_url)
    try:
        if task.pr_number is not None and await github.is_pull_request_open(repo, task.pr_number):
            await github.close_pull_request(repo, task.pr_number)
        if is_task_branch(project, task.branch):
            await github.delete_branch(repo, task.branch)
        await remove_task_worktree(project, task)
        task.worktree_path = None
    except github.GitHubError as exc:
        log.warning("Task #%s (%s): clean-up incomplete: %s", task.id, task.status.value, exc)


async def clean_up_finished_tasks(s: AsyncSession) -> int:
    """Clean up every done or cancelled task in the database (the backlog). Only the branches
    recorded on those tasks are touched. Returns how many tasks were visited."""
    tasks = (
        await s.scalars(select(Task).where(Task.status.in_([TaskStatus.done, TaskStatus.cancelled])))
    ).all()
    projects: dict[int, Project] = {}
    for task in tasks:
        if task.project_id not in projects:
            projects[task.project_id] = await s.get(Project, task.project_id)
        project = projects[task.project_id]
        if project is not None and project.repo_url and (task.branch or task.pr_number is not None):
            await clean_up_task(project, task)
    await s.commit()
    return len(tasks)


async def merge_task(
    s: AsyncSession, project_id: int, task_id: int, author: Employee | None, force: bool = False, message: str = ""
) -> Task:
    """Merge a task's PR. author None = the boss, who may `force` past the merge rules.
    message: what the author tells the team (the PR link is added)."""
    project = await s.get(Project, project_id)
    task = await get_task(s, project_id, task_id)
    if task.status != TaskStatus.review or task.pr_number is None:
        raise WorkflowError(f"Task #{task.id} has no pull request waiting to be merged")
    if not force and (blockers := await merge_blockers(s, project, task)):
        raise WorkflowError("Cannot merge yet: " + "; ".join(blockers))

    repo = github.repo_slug(project.repo_url)
    await github.merge_pull_request(repo, task.pr_number, task.pr_title or f"[#{task.id}] {task.title}")
    task.status = TaskStatus.done
    await clean_up_task(project, task)
    emit_event(s, project_id, "pr_merged", {"task_id": task.id, "pr_url": task.pr_url})
    await announce(s, task, "Merged" + (f" by {author.name}" if author else ""))
    await s.flush()

    # Wake up the assignees of tasks that were only waiting for this one
    waiting = await s.scalars(
        select(Task).where(Task.project_id == project_id, Task.status == TaskStatus.todo)
    )
    for other in waiting:
        if task.id in other.depends_on and other.assignee_id:
            statuses = await s.scalars(select(Task.status).where(Task.id.in_(other.depends_on)))
            if all(st == TaskStatus.done for st in statuses):
                emit_event(s, project_id, "task_unblocked", {"task_id": other.id}, employee_id=other.assignee_id)

    if author is not None:  # The boss merging from the app needs no announcement
        await post_message(s, project_id, task.conversation_id, f"{message.strip()} {task.pr_url}".strip(), author)
    return task
