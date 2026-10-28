"""Tasks that became mergeable without a review (CI turned green) or that nobody merged:
the lead is woken up, then reminded once. Same for the CI of the release PR and of production."""

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import github, workflow
from app.config import settings
from app.models import Project, Task, TaskStatus
from app.services import emit_event, post_system_message, team_conversation_id

# Seconds between two merge-rule checks of the same task (they ask GitHub about the CI)
CHECK_EVERY_S = 60
_last_check: dict[int, float] = {}
_last_release_check: dict[int, float] = {}

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
        except github.GitHubError as exc:
            log.warning("Task #%s: merge rules could not be checked: %s", task.id, exc)
            continue  # One broken task must not stop the others
        if blockers:
            task.merge_ready_at = None  # A rule broke again (CI): announce it when fixed
            continue
        if reminder_due:
            await workflow.remind_merge(s, task)
        else:
            await workflow.mark_merge_ready(s, task, "the checks")
    await s.commit()


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
            await _announce_ci(
                s, project, "main_ci", {"branch": production, "sha": sha, "result": result},
                f"CI of {production} after the release: {result}",
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
            f"CI of the release PR #{pr['number']}: {result} · {pr['html_url']}",
        )  # fmt: skip
        project.release_ci_sha = pr["head"]["sha"]
