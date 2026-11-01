"""Tasks that became mergeable without a review (CI turned green) or that nobody merged:
the lead is woken up, then reminded once. Tasks stuck in review (conflict, no CI, red CI) go back
to their dev, once per head SHA. Same for the CI of the release PR and of production."""

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import github, projects, release, workflow
from app.config import settings
from app.company.catalog import REVIEWER_KEY, Role, held_role_keys, load_catalog
from app.models import AgentRun, Employee, Event, Project, Review, Task, TaskStatus, Wakeup
from app.services import emit_event, post_system_message, team_conversation_id

# Seconds between two merge-rule checks of the same task (they ask GitHub about the CI)
CHECK_EVERY_S = 60
_last_check: dict[int, float] = {}
_last_release_check: dict[int, float] = {}
_last_idle_check: dict[int, float] = {}
_last_unstarted_check: dict[int, float] = {}
_last_pending_check: dict[int, float] = {}
# Last final CI result announced to the lead, per task; in memory, so a restart may repeat one
_ci_seen: dict[int, str] = {}

log = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def watch_mergeable_tasks(s: AsyncSession) -> None:
    now = time.monotonic()
    tasks = await s.scalars(
        select(Task).where(Task.status == TaskStatus.review, Task.pr_number.is_not(None))
    )
    tasks = list(tasks)
    for gone in _last_check.keys() - {t.id for t in tasks}:
        del _last_check[gone]
    for gone in _ci_seen.keys() - {t.id for t in tasks}:
        del _ci_seen[gone]
    for task in tasks:
        reminder_due = (
            task.merge_ready_at is not None
            and task.lead_reminded_at is None
            and _aware(task.merge_ready_at) <= datetime.now(UTC) - timedelta(minutes=settings.merge_reminder_minutes)
        )
        if task.merge_ready_at is not None and not reminder_due:
            continue
        if task.merge_ready_at is None and now - _last_check.get(task.id, -CHECK_EVERY_S) < CHECK_EVERY_S:
            continue
        _last_check[task.id] = now
        project = await s.get(Project, task.project_id)
        try:
            blockers = await workflow.merge_blockers(s, project, task)
            stuck = await _stuck(project, task, blockers)
        except github.GitHubError as exc:
            log.warning("Task #%s: merge rules could not be checked: %s", task.id, exc)
            continue  # One broken task must not stop the others
        if stuck is not None:
            await _send_back(s, project, task, *stuck)
            continue
        if (ci := _ci_result(blockers)) is not None and _ci_seen.get(task.id) != ci:
            if ci != "green" or blockers:  # All green and approved: the lead is woken as mergeable
                workflow.wake_lead(task, f"CI finished: {ci}")
            _ci_seen[task.id] = ci
        if task.merge_retry_at is not None and not any(b.startswith("CI still running") for b in blockers):
            task.merge_retry_at = None  # The CI is over; mergeable tasks wake the lead just below
            if blockers:
                payload = {"task_id": task.id, "result": "; ".join(blockers)}
                emit_event(s, task.project_id, "merge_retry", payload, role="lead")
        if blockers:
            task.merge_ready_at = None  # A rule broke again (CI): announce it when fixed
            continue
        if reminder_due:
            await workflow.remind_merge(s, task)
        else:
            await workflow.mark_merge_ready(s, task, "the checks")
    await s.commit()


def _ci_result(blockers: list[str]) -> str | None:
    """"green" or the failure reason once the CI is over; None while it runs or is missing."""
    ci = next((b for b in blockers if b.startswith(("CI", "no CI"))), None)
    if ci is None:
        return "green"
    return None if ci.startswith(("CI still running", "no CI")) else ci


async def _stuck(project: Project, task: Task, blockers: list[str]) -> tuple[str, str] | None:
    """(head SHA, what the dev must fix) if the PR cannot merge by itself and the dev was not
    already told for this head; the CI reasons come from merge_blockers, so they follow the
    company's rules (a size that does not require CI never complains about it)."""
    if task.assignee_id is None:
        return None
    pr = await github.get_pull_request(github.repo_slug(project.repo_url), task.pr_number)
    sha = pr["head"]["sha"]
    if task.stuck_sha == sha:
        return None
    if pr.get("mergeable_state") == "dirty":
        return sha, f"conflict with {pr['base']['ref']}: rebase and submit again"
    for blocker in blockers:
        if blocker.startswith("CI failed") and len(blockers) == 1:  # Approved, only the CI is red
            return sha, blocker
        if blocker.startswith("no CI checks") and task.submitted_at is not None and (
            _aware(task.submitted_at) <= datetime.now(UTC) - timedelta(minutes=settings.ci_missing_minutes)
        ):
            return sha, f"no CI reported after {settings.ci_missing_minutes} minutes: check the workflows and push again"
    return None


async def _send_back(s: AsyncSession, project: Project, task: Task, sha: str, problem: str) -> None:
    """Give the task back to its dev with the problem, and tell the team."""
    task.status, task.stuck_sha, task.merge_ready_at = TaskStatus.changes_requested, sha, None
    await workflow.wake_dev(s, task, "pr_blocked", {"problem": problem})
    # The CI output only goes to the dev: the lead and the team channel get the headline
    headline = problem.split("\n", 1)[0]
    workflow.wake_lead(task, f"sent back to its dev: {headline}")
    if (conversation_id := await team_conversation_id(s, project.id)) is not None:
        await post_system_message(s, conversation_id, f"#{task.id} {task.title} sent back to its dev: {headline} · {task.pr_url or ''}".strip())


async def watch_idle_tasks(s: AsyncSession) -> None:
    """Alert the lead, once per head SHA, about a task in progress or in review that has not moved
    for idle_task_minutes, with the reason it is stuck."""
    now = time.monotonic()
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.idle_task_minutes)
    tasks = list(
        await s.scalars(
            select(Task).where(Task.status.in_([TaskStatus.in_progress, TaskStatus.review]), Task.updated_at < cutoff)
        )
    )
    for gone in _last_idle_check.keys() - {t.id for t in tasks}:
        del _last_idle_check[gone]
    for task in tasks:
        if now - _last_idle_check.get(task.id, -CHECK_EVERY_S) < CHECK_EVERY_S:
            continue
        _last_idle_check[task.id] = now
        # The task row does not change while its dev works: a running agent is activity (a run older
        # than the timeout was cut by a restart and never finished)
        started_after = datetime.now(UTC) - timedelta(seconds=settings.agent_timeout_s)
        running = await s.scalar(
            select(AgentRun.id)
            .where(AgentRun.task_id == task.id, AgentRun.finished_at.is_(None), AgentRun.started_at > started_after)
            .limit(1)
        )
        if running is not None:
            continue
        project = await s.get(Project, task.project_id)
        try:
            sha, reason = await _idle_reason(s, project, task)
        except github.GitHubError as exc:
            log.warning("Task #%s: idle state could not be checked: %s", task.id, exc)
            continue
        if reason is None:
            continue  # Already alerted for this head SHA
        task.idle_alert_sha = sha
        payload = {"task_id": task.id, "status": task.status.value, "minutes": settings.idle_task_minutes, "reason": reason}
        emit_event(s, task.project_id, "task_idle", payload, role="lead")
    await s.commit()


async def watch_silent_reviews(s: AsyncSession) -> None:
    """A task in review with no reviewer verdict for review_silence_minutes: wake the reviewers up
    again (when none is busy) and tell the lead. Waits another delay before the next reminder."""
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.review_silence_minutes)
    tasks = await s.scalars(select(Task).where(Task.status == TaskStatus.review, Task.pr_number.is_not(None)))
    roles = load_catalog()["roles"]
    for task in list(tasks):
        reviews = await workflow.task_reviews(s, task)
        if await _review_silent_since(s, task, reviews) >= cutoff:
            continue
        if workflow.reviewer_gave_verdict(reviews, task, roles):
            continue
        await _remind_reviewers(s, task, roles)
    await s.commit()


async def _review_silent_since(s: AsyncSession, task: Task, reviews: list[Review]) -> datetime:
    """The last sign of life of the review: submission, opinion or reminder."""
    moments = [_aware(r.created_at) for r in reviews]
    if task.submitted_at is not None:
        moments.append(_aware(task.submitted_at))
    reminders = await s.scalars(
        select(Event.created_at).where(
            Event.type == "review_overdue", Event.project_id == task.project_id,
            Event.payload["task_id"].as_integer() == task.id,
        )
    )  # fmt: skip
    moments += [_aware(m) for m in reminders]
    return max(moments, default=datetime.min.replace(tzinfo=UTC))


async def _remind_reviewers(s: AsyncSession, task: Task, roles: dict[str, Role]) -> None:
    employees = await s.scalars(select(Employee).where(Employee.project_id == task.project_id))
    reviewers = [e for e in employees if REVIEWER_KEY in held_role_keys(e.roles, roles) and e.id != task.assignee_id]
    busy = await s.scalar(
        select(Wakeup.id).where(Wakeup.employee_id.in_([e.id for e in reviewers]), Wakeup.finished_at.is_(None)).limit(1)
    )
    if not reviewers or busy is not None:
        return
    payload = {"task_id": task.id, "pr_url": task.pr_url, "minutes": settings.review_silence_minutes}
    for reviewer in reviewers:  # Not by role: the assignee must never be asked to review their own PR
        emit_event(s, task.project_id, "review_overdue", payload, employee_id=reviewer.id)
    emit_event(s, task.project_id, "review_stalled", payload, role="lead")


async def _idle_reason(s: AsyncSession, project: Project, task: Task) -> tuple[str, str | None]:
    """(head SHA, why the task is stuck); the SHA is "none" while there is no PR. The reason is
    None when the lead was already alerted for this SHA: only one PR call is spent then."""
    if task.status != TaskStatus.review or task.pr_number is None:
        return "none", None if task.idle_alert_sha == "none" else "no activity on the work in progress"
    pr = await github.get_pull_request(github.repo_slug(project.repo_url), task.pr_number)
    sha = pr["head"]["sha"]
    if task.idle_alert_sha == sha:
        return sha, None
    if pr.get("mergeable_state") == "dirty":
        return sha, f"the PR conflicts with {pr['base']['ref']}"
    blockers = await workflow.merge_blockers(s, project, task)
    return sha, "; ".join(blockers) or "every merge rule is met, waiting to be merged"


def _ci_over(reason: str | None) -> bool:
    """Whether commit_checks' answer is final: green, or red once every check has completed."""
    return reason is None or not reason.startswith(("CI still running", "no CI checks"))


async def _announce_ci(s: AsyncSession, project: Project, event: str, payload: dict, line: str) -> None:
    emit_event(s, project.id, event, payload, role="lead")
    if (conversation_id := await team_conversation_id(s, project.id)) is not None:
        await post_system_message(s, conversation_id, line)


async def watch_release_ci(s: AsyncSession) -> None:
    """Wake the lead, once per head SHA, when CI ends on the open release PR (team's branch to
    production) and, after merge_release, on production's head."""
    now = time.monotonic()
    projects = list(await s.scalars(select(Project).where(Project.kind == "company")))
    for gone in _last_release_check.keys() - {p.id for p in projects}:
        del _last_release_check[gone]
    for project in projects:
        if not project.repo_url or now - _last_release_check.get(project.id, -CHECK_EVERY_S) < CHECK_EVERY_S:
            continue
        _last_release_check[project.id] = now
        try:
            await _watch_project_ci(s, project)
        except github.GitHubError as exc:
            log.warning("Project #%s: release CI could not be checked: %s", project.id, exc)
    await s.commit()


async def _watch_project_ci(s: AsyncSession, project: Project) -> None:
    repo = github.repo_slug(project.repo_url)
    production = await github.resolve_branch(repo, "")
    if project.default_branch == production:
        return
    if project.main_ci_watch:
        sha = await github.branch_head(repo, production)
        reason = await github.commit_checks(repo, sha)
        if sha == project.main_ci_sha:
            project.main_ci_watch = False
        elif _ci_over(reason):
            result = "green" if reason is None else f"red ({reason})"
            version = await _published_version(repo, sha) if reason is None else None
            if reason is not None:
                next_step = "Get it fixed."
            elif version:
                next_step = f"Publish v{version} now with publish_version."
            else:
                next_step = "Tag it with publish_version."
            line = f"CI of {production} after the release: {result.split(chr(10), 1)[0]}" + (f" · publish v{version}" if version else "")
            await _announce_ci(
                s, project, "main_ci", {"branch": production, "sha": sha, "result": result, "next_step": next_step}, line,
            )  # fmt: skip
            project.main_ci_sha, project.main_ci_watch = sha, False
    pr = await github.find_pull_request(repo, project.default_branch, production)
    if pr is None or pr["head"]["sha"] == project.release_ci_sha:
        return
    reason = await github.commit_checks(repo, pr["head"]["sha"])
    if _ci_over(reason):
        result = "green" if reason is None else f"red ({reason})"
        await _announce_ci(
            s, project, "release_ci", {"pr_number": pr["number"], "sha": pr["head"]["sha"], "result": result},
            f"CI of the release PR #{pr['number']}: {result.split(chr(10), 1)[0]} · {pr['html_url']}",
        )  # fmt: skip
        project.release_ci_sha = pr["head"]["sha"]


async def _published_version(repo: str, sha: str) -> str | None:
    """The version the files of `sha` carry, the one to tag; None if it cannot be read."""
    try:
        text = await github.file_content(repo, "frontend/package.json", sha)
        return projects.VERSION_FILES["frontend/package.json"](text, "") if text else None
    except (github.GitHubError, ValueError):
        return None


async def watch_pending_release(s: AsyncSession) -> None:
    """Wake the lead, once per head SHA of the team's branch, when it holds commits production lacks,
    no task is open and nothing moved for release_wait_minutes: the release must not depend on a memory."""
    now = time.monotonic()
    found = list(await s.scalars(select(Project).where(Project.kind == "company")))
    for gone in _last_pending_check.keys() - {p.id for p in found}:
        del _last_pending_check[gone]
    for project in found:
        if not project.repo_url or now - _last_pending_check.get(project.id, -CHECK_EVERY_S) < CHECK_EVERY_S:
            continue
        _last_pending_check[project.id] = now
        open_task = await s.scalar(
            select(Task.id).where(Task.project_id == project.id, Task.status.not_in([TaskStatus.done, TaskStatus.cancelled])).limit(1)
        )
        if open_task is not None:
            continue
        try:
            await _watch_pending(s, project)
        except (github.GitHubError, projects.WorkflowError) as exc:
            log.warning("Project #%s: pending release could not be checked: %s", project.id, exc)
    await s.commit()


async def _watch_pending(s: AsyncSession, project: Project) -> None:
    repo = github.repo_slug(project.repo_url)
    tip = await github.branch_tip(repo, project.default_branch)
    if tip["sha"] == project.release_reminded_sha or tip["message"].startswith("chore(release)"):
        return  # Told already, or the bump is there and its CI will wake the lead
    committed = datetime.fromisoformat(tip["date"].replace("Z", "+00:00"))
    if committed > datetime.now(UTC) - timedelta(minutes=settings.release_wait_minutes):
        return
    plan = await projects.release_plan(project)
    if plan is None or plan["ahead"] == 0:
        return
    changes = github.frame_untrusted(
        release.changelog_body(plan["commits"]), github.COMMIT_MESSAGES_START, github.COMMIT_MESSAGES_END
    )
    payload = {"sha": tip["sha"], "version": plan["version"], "count": plan["ahead"], "changes": changes}
    project.release_reminded_sha = tip["sha"]
    await _announce_ci(
        s, project, "release_pending", payload,
        f"{plan['ahead']} commits of {project.default_branch} wait for a release: v{plan['version']}",
    )  # fmt: skip


async def watch_unstarted_tasks(s: AsyncSession) -> None:
    """A todo or changes_requested task with a dev but no run for idle_task_minutes: the dev is
    nudged once, then (after another idle_task_minutes) the lead is told."""
    now = time.monotonic()
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.idle_task_minutes)
    tasks = list(
        await s.scalars(
            select(Task).where(
                Task.status.in_([TaskStatus.todo, TaskStatus.changes_requested]),
                Task.assignee_id.is_not(None),
                Task.unstarted_nudges < 2,
                Task.updated_at < cutoff,
            )
        )
    )
    for gone in _last_unstarted_check.keys() - {t.id for t in tasks}:
        del _last_unstarted_check[gone]
    for task in tasks:
        if now - _last_unstarted_check.get(task.id, -CHECK_EVERY_S) < CHECK_EVERY_S:
            continue
        _last_unstarted_check[task.id] = now
        if not await workflow.dependencies_done(s, task) or await workflow.dev_busy(s, task):
            continue  # Waiting for other tasks, or already on it
        last_run = await s.scalar(select(func.max(AgentRun.started_at)).where(AgentRun.task_id == task.id))
        last_wakeup = await s.scalar(select(func.max(Wakeup.created_at)).where(Wakeup.task_id == task.id))
        if any(at is not None and _aware(at) >= cutoff for at in (last_run, last_wakeup)):
            continue
        if task.unstarted_nudges == 0:
            why = f"no run for {settings.idle_task_minutes} minutes"
            await workflow.wake_dev(s, task, "task_nudge", {"why": why}, nudge=True)
        else:
            payload = {
                "task_id": task.id, "status": task.status.value, "minutes": settings.idle_task_minutes,
                "reason": "its dev was nudged and still did not start",
            }  # fmt: skip
            emit_event(s, task.project_id, "task_idle", payload, role="lead")
        task.unstarted_nudges += 1
    await s.commit()
