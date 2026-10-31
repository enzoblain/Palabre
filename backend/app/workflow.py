"""Task lifecycle: creation, assignment, review and merge, with the mode's merge gates."""

import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import github
from app.config import settings
from app.company.team import load_catalog
from app.models import Employee, Event, Project, Review, Task, TaskKind, TaskStatus, Verdict, Wakeup
from app.errors import ErrorCode
from app.sensitive_paths import touches_sensitive_paths
from app.errors import WorkflowError
from app.services import emit_event, post_message, post_system_message
from app.worktrees import (
    final_branch_name,
    push_task_branch,
    refresh_clone,
    remove_task_worktree,
    rename_branch,
    repo_dir,
)

MAX_DIFF_CHARS = 100_000
# Events that make a dev work on a task (the same set as the orchestrator's task runs)
TASK_EVENT_TYPES = {"task_assigned", "task_unblocked", "changes_requested", "pr_blocked", "task_retry", "task_resume", "task_nudge"}
EDITABLE_STATUSES = {TaskStatus.todo, TaskStatus.cancelled}

log = logging.getLogger(__name__)


# Changes of each task waiting to reach the lead: (project id, first seen at, changes). In memory:
# a restart loses at most the last window, and the idle watchdog catches what stays stuck.
_lead_pending: dict[int, tuple[int, float, list[str]]] = {}


def wake_lead(task: Task, change: str) -> None:
    """Note a task change for the lead; flush_lead_updates sends the changes of a task together
    once lead_debounce_seconds have passed since the first one."""
    task.idle_alert_sha = None  # The task moved: a new stall deserves a new alert
    _, since, changes = _lead_pending.get(task.id, (task.project_id, time.monotonic(), []))
    _lead_pending[task.id] = (task.project_id, since, [*changes, change])


def flush_lead_updates(s: AsyncSession) -> None:
    """Emit one task_update per task whose window is over, with all its changes."""
    now = time.monotonic()
    for task_id, (project_id, since, changes) in list(_lead_pending.items()):
        if now - since >= settings.lead_debounce_seconds:
            del _lead_pending[task_id]
            emit_event(s, project_id, "task_update", {"task_id": task_id, "change": "; ".join(changes)}, role="lead")


async def wake_dev(
    s: AsyncSession, task: Task, event_type: str, payload: dict | None = None, *, dedupe: bool = False, nudge: bool = False
) -> bool:
    """The one way to send a task back to its dev: emit event_type for the assignee with the reason in
    payload. dedupe: skip if a run is on it or a wakeup is already queued. Returns whether it woke."""
    if task.assignee_id is None:
        return False
    if dedupe and await dev_busy(s, task):
        return False
    if not nudge:
        task.unstarted_nudges = 0  # Someone moved the task: the watchdog starts over
    task.idle_alert_sha = None
    emit_event(s, task.project_id, event_type, {"task_id": task.id, **(payload or {})}, employee_id=task.assignee_id)
    return True


async def dev_busy(s: AsyncSession, task: Task) -> bool:
    """A wakeup of this task is queued or running, or an event for it is not resolved yet."""
    if await s.scalar(select(Wakeup.id).where(Wakeup.task_id == task.id, Wakeup.finished_at.is_(None)).limit(1)):
        return True
    queued = await s.scalars(
        select(Event).where(Event.processed_at.is_(None), Event.target_employee_id == task.assignee_id)
    )
    return any(e.type in TASK_EVENT_TYPES and e.payload.get("task_id") == task.id for e in queued)


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


async def dependencies_done(s: AsyncSession, task: Task) -> bool:
    if not task.depends_on:
        return True
    statuses = await s.scalars(select(Task.status).where(Task.id.in_(task.depends_on)))
    return all(st == TaskStatus.done for st in statuses)


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
        raise WorkflowError(f"Task #{task_id} is {task.status.value} and can no longer be reassigned", code=ErrorCode.TASK_WRONG_STATUS)
    employee = await find_employee(s, project_id, assignee)
    changed = task.assignee_id != employee.id
    task.assignee, task.assignee_id = employee, employee.id  # The relationship too: it is what get_task shows
    # Same assignee: only a nudge, which does nothing if the dev is already on it
    await wake_dev(s, task, "task_assigned", dedupe=not changed)
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
    author: Employee | None = None,
) -> Task:
    """author: who edits (None = the boss); recorded when they cancel the task."""
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
            raise WorkflowError("Status can only be set to 'todo' or 'cancelled'; the rest follows the workflow", code=ErrorCode.TASK_WRONG_STATUS)
        was_cancelled = task.status == TaskStatus.cancelled
        task.status = new_status
        if new_status == TaskStatus.cancelled and not was_cancelled:
            task.closed_by_id = author.id if author else None
            task.closed_at = datetime.now(UTC)
            await clean_up_task(await s.get(Project, project_id), task)
        elif new_status == TaskStatus.todo and await dependencies_done(s, task):
            why = "rebase and submit again" if task.pr_number is not None else "back in todo"
            await wake_dev(s, task, "task_nudge", {"why": why}, dedupe=True)
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


async def _changed_files(project: Project, task: Task) -> list[str]:
    """Files of the pushed branch (not the agent's HEAD), read in the reference clone the backend owns.
    No rename detection, so both sides of a move are listed; -z keeps non-ASCII paths unquoted."""
    out = await github.git(
        repo_dir(project), "diff", "--no-ext-diff", "--no-renames", "--name-only", "-z",
        f"origin/{project.default_branch}...origin/{task.branch}",
    )  # fmt: skip
    return out.split("\0")


async def _pushed_head(project: Project, task: Task) -> str:
    """SHA of the pushed task branch in the reference clone; empty when it cannot be read."""
    try:
        return (await github.git(repo_dir(project), "rev-parse", f"origin/{task.branch}")).strip()
    except github.GitHubError as e:
        log.warning("head of task %s unreadable: %s", task.id, e)
        return ""


async def _is_pure_rebase(project: Project, task: Task, head: str) -> bool:
    """Replaying the reviewed commit onto the base the branch now sits on gives exactly the new tree.
    Exact, unlike a patch-id, which ignores where a hunk applies. Any failure (conflict, reviewed
    commit gone) is False: a new round starts."""
    reviewed = task.reviewed_head
    if not reviewed or not head:
        return False
    repo = repo_dir(project)
    try:
        base = (await github.git(repo, "merge-base", f"origin/{project.default_branch}", head)).strip()
        replayed = (await github.git(repo, "merge-tree", "--write-tree", base, reviewed)).split("\n")[0].strip()
        tree = (await github.git(repo, "rev-parse", f"{head}^{{tree}}")).strip()
    except github.GitHubError as e:
        log.warning("rebase check of task %s failed: %s", task.id, e)
        return False
    return bool(replayed) and replayed == tree


async def _keep_reviewed_head(project: Project, task: Task, head: str) -> None:
    """A ref keeps the reviewed commit from being garbage collected after a force-push."""
    try:
        await github.git(repo_dir(project), "update-ref", f"refs/palabre/reviewed/{task.id}", head)
    except github.GitHubError as e:
        log.warning("cannot keep reviewed head of task %s: %s", task.id, e)


async def _changes_pending(s: AsyncSession, task: Task) -> bool:
    """A reviewer's latest verdict of the current round is 'changes'."""
    reviews = await s.scalars(
        select(Review).where(Review.task_id == task.id, Review.round == task.review_round).order_by(Review.id)
    )
    latest: dict[int, Verdict] = {}
    for r in reviews:
        if r.verdict != Verdict.comment:
            latest[r.reviewer_id] = r.verdict
    return Verdict.changes in latest.values()


async def start_task(s: AsyncSession, project_id: int, task_id: int, employee: Employee) -> Task:
    """Wake the assignee up on their task (from a conversation): the work itself only
    happens in a task run, in the task's worktree."""
    task = await get_task(s, project_id, task_id)
    if task.assignee_id != employee.id:
        raise WorkflowError(f"Task #{task.id} is not assigned to you", code=ErrorCode.TASK_NOT_YOURS)
    if task.status not in {TaskStatus.todo, TaskStatus.in_progress, TaskStatus.changes_requested}:
        raise WorkflowError(f"Task #{task.id} is {task.status.value}: there is nothing to work on", code=ErrorCode.TASK_WRONG_STATUS)
    if task.depends_on:
        statuses = await s.scalars(select(Task.status).where(Task.id.in_(task.depends_on)))
        if any(st != TaskStatus.done for st in statuses):
            raise WorkflowError(f"Task #{task.id} is still waiting for tasks {task.depends_on}", code=ErrorCode.TASK_WAITING_FOR_DEPENDENCIES)
    task.idle_alert_sha = None  # Back at work: a new stall deserves a new alert
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
            "The PR number is added for you.",
            code=ErrorCode.INVALID_PR_TITLE,
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
        raise WorkflowError("Only the assignee can submit this task for review", code=ErrorCode.TASK_NOT_YOURS)
    if task.status not in {TaskStatus.in_progress, TaskStatus.changes_requested}:
        raise WorkflowError(f"Task #{task.id} is {task.status.value}, it cannot be submitted", code=ErrorCode.TASK_WRONG_STATUS)
    if not task.branch or not task.worktree_path:
        raise WorkflowError("This task has no branch yet", code=ErrorCode.TASK_NO_BRANCH)
    bare_title = conventional_title(title)
    if task.pr_number is None and github.is_task_branch_name(task.branch):
        # First submission: the branch gets its standard `<type>/<id>-<slug>` name before any push
        await rename_branch(task, final_branch_name(bare_title, task.id))
    if await _commits_ahead(project, task) == 0:
        raise WorkflowError("No commits on your branch: commit your work before submitting", code=ErrorCode.NO_COMMITS)

    repo = github.repo_slug(project.repo_url)
    # The task branch belongs to its assignee alone: a rebased branch is force-pushed,
    # unless someone else pushed to it in the meantime (lease)
    await push_task_branch(project, task)
    changed_files = await _changed_files(project, task)
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

    head = await _pushed_head(project, task)
    # The gate is derived from the changed files; the author's flag can only add it, never remove it
    sensitive_now = task.sensitive or sensitive or touches_sensitive_paths(changed_files)
    # Same content as the reviewed round, nobody asked for changes and no new gate: only the base
    # moved, so the approvals stay and the merge just waits for the CI on the new head
    pure_rebase = (
        task.review_round > 0
        and task.reviewed_head is not None
        and sensitive_now == task.sensitive
        and not await _changes_pending(s, task)
        and await _is_pure_rebase(project, task, head)
    )
    task.status = TaskStatus.review
    task.submitted_at = datetime.now(UTC)
    if pure_rebase:
        # Like a normal submission: merge_watch follows the CI of the new head only while this is unset
        task.merge_ready_at = task.lead_reminded_at = None
        await announce(s, task, f"PR rebased by {author.name}, content unchanged: approvals kept (round {task.review_round})")
        wake_lead(task, f"PR rebased by {author.name}, approvals kept")
        await post_message(s, project_id, task.conversation_id, f"{message.strip()} {task.pr_url}".strip(), author)
        return task
    task.reviewed_head = head or None
    if head:
        await _keep_reviewed_head(project, task, head)
    task.review_round += 1
    task.merge_ready_at = task.lead_reminded_at = None
    task.sensitive = sensitive_now
    process = mode_process(project.mode)
    payload = {"task_id": task.id, "pr_url": task.pr_url}
    emit_event(s, project_id, "review_requested", payload, role="reviewer")
    if process["qa_gate"]:
        emit_event(s, project_id, "pr_ready", payload, role="qa")
    if process["security_gate"] and task.sensitive:
        emit_event(s, project_id, "sensitive_pr", payload, role="security")
    await announce(s, task, f"PR submitted by {author.name} (round {task.review_round})")
    wake_lead(task, f"PR submitted by {author.name} (round {task.review_round})")
    # In the author's own words, with the link
    await post_message(s, project_id, task.conversation_id, f"{message.strip()} {task.pr_url}".strip(), author)
    return task


def _task_checkout(project: Project, task: Task) -> tuple[Path, str]:
    """Where to read the task's branch: its own clone, or, once that is gone (merged or
    cancelled), the pushed branch in the project's clone."""
    if task.worktree_path and Path(task.worktree_path).exists():
        return Path(task.worktree_path), task.branch
    return repo_dir(project), f"origin/{task.branch}"


async def get_diff(s: AsyncSession, project_id: int, task_id: int) -> str:
    project = await s.get(Project, project_id)
    task = await get_task(s, project_id, task_id)
    if not task.branch:
        raise WorkflowError(f"Task #{task.id} has no branch yet", code=ErrorCode.TASK_NO_BRANCH)
    repo, head = _task_checkout(project, task)
    if repo != repo_dir(project):
        await refresh_clone(project, repo)  # Diff against the last fetched state if GitHub fails
    else:
        try:
            await github.git(repo, "fetch", "--quiet", "origin", project.default_branch, repo_url=project.repo_url)
        except github.GitHubError:
            pass
    base = f"origin/{project.default_branch}...{head}"
    # No external diff or textconv driver: the clone's config is written by the agent
    stat = await github.git(repo, "diff", "--no-ext-diff", "--no-textconv", "--stat", base)
    diff = await github.git(repo, "diff", "--no-ext-diff", "--no-textconv", base)
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
        raise WorkflowError(f"Task #{task.id} is {task.status.value}, not waiting for review", code=ErrorCode.TASK_WRONG_STATUS)
    if task.assignee_id == reviewer.id:
        raise WorkflowError("You cannot review your own task", code=ErrorCode.CANNOT_REVIEW_OWN_TASK)

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
    wake_lead(task, f"{reviewer.name} ({reviewer.title}) {_VERDICT_LABELS[review.verdict]}")
    payload = {"task_id": task.id, "reviewer": reviewer.name}
    if review.verdict == Verdict.changes:
        task.status = TaskStatus.changes_requested
        await wake_dev(s, task, "changes_requested", payload)
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
        repo, head = _task_checkout(project, task)
        files = (
            await github.git(repo, "diff", "--no-ext-diff", "--name-only", f"origin/{project.default_branch}...{head}")
        ).split()
        # The CHANGELOG is generated at release: the docs to update are the README or the docs/ folder
        if not any(PurePosixPath(f).name.upper().startswith("README") or "docs" in PurePosixPath(f).parts[:-1] for f in files):
            blockers.append("the README or docs/ were not updated")
    return blockers


def is_task_branch(project: Project, branch: str | None) -> bool:
    """Only a task's own branch may be deleted: never the default branch, `dev` or a release."""
    return github.is_task_branch_name(branch) and branch not in {project.default_branch, github.WORKING_BRANCH}


async def _drop_reviewed_head(project: Project, task: Task) -> None:
    """Release the ref of _keep_reviewed_head so the reference clone stops pinning the objects."""
    try:
        await github.git(repo_dir(project), "update-ref", "-d", f"refs/palabre/reviewed/{task.id}")
    except github.GitHubError as e:
        log.warning("cannot drop reviewed head of task %s: %s", task.id, e)


async def clean_up_task(project: Project, task: Task) -> None:
    """A finished task leaves nothing behind: its PR is closed if still open, its branch is
    deleted on GitHub and locally, and its worktree removed. Idempotent; a GitHub or git
    error is logged and never blocks the caller (the status change is already done)."""
    repo = github.repo_slug(project.repo_url)
    await _drop_reviewed_head(project, task)
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
        raise WorkflowError(f"Task #{task.id} has no pull request waiting to be merged", code=ErrorCode.TASK_NO_PULL_REQUEST)
    if not force and (blockers := await merge_blockers(s, project, task)):
        if any(b.startswith("CI still running") for b in blockers):
            task.merge_retry_at = datetime.now(UTC)  # The watcher wakes the lead when the CI is over
            await s.commit()
        raise WorkflowError("Cannot merge yet: " + "; ".join(blockers), code=ErrorCode.MERGE_BLOCKED)

    repo = github.repo_slug(project.repo_url)
    await github.merge_pull_request(repo, task.pr_number, task.pr_title or f"[#{task.id}] {task.title}")
    task.status = TaskStatus.done
    task.closed_by_id = author.id if author else None
    task.closed_at = datetime.now(UTC)
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
