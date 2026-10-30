"""Runs the wakeups: at most one run per employee, and a limit per Claude account."""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import services
from app import credits
from app.accounts import assign_accounts, token_for
from app.company.team import effort_for, render_system_prompt
from app.config import settings
from app.db import SessionLocal
from app.github import GitHubError
from app.mcp_server.permissions import claude_tools_for, mcp_tools_for
from app.models import AgentRun, AgentSession, Employee, Event, Message, Project, Task, TaskStatus, Wakeup
from app.orchestrator.context_reset import reset_context_if_due, reset_session_if_worn, resumable
from app.orchestrator.credit_watch import on_limit_reached, on_run_succeeded
from app.orchestrator.events import expand_events
from app.orchestrator.prompts import (
    CHAT_RULES,
    RESEARCH_RULES,
    language_rule,
    operating_rules,
    orientation_rule,
    task_rules,
    version_rule,
    wake_prompt,
)
from app.orchestrator.retries import RUNNABLE_TASK_STATUSES, on_task_run_failed
from app.orchestrator.scheduler import run_scheduler
from app.projects import team_of
from app.runner import ClaudeRunError, RunResult, RunSpec, SessionNotFound, UsageLimitReached, run_claude
from app.worktrees import desk_dir, prepare_desk, prepare_worktree, repo_dir, sync_repo

log = logging.getLogger(__name__)

REPO_SYNC_INTERVAL_S = 60
# Wakeups that only come from the team talking to itself: the ones the throttle applies to
CHATTER_EVENTS = {"mention", "conversation_idle", "daily"}


class SkipRun(Exception):
    """The wakeup is no longer relevant (task done, guard tripped, ...)."""


class Throttled(Exception):
    """Too much chatter for this employee: the wakeups stay queued until `until`."""

    def __init__(self, message: str, until: datetime) -> None:
        super().__init__(message)
        self.until = until


class Orchestrator:
    def __init__(self) -> None:
        self._loops: list[asyncio.Task] = []
        self._runs: dict[int, asyncio.Task] = {}  # employee id → its current run
        self._run_accounts: dict[int, int] = {}  # employee id → account of its current run
        self._repo_synced_at: dict[int, float] = {}
        self._throttled_at: dict[tuple[int, int], datetime] = {}

    @property
    def running_employee_ids(self) -> list[int]:
        return sorted(self._runs)

    async def start(self) -> None:
        async with SessionLocal() as s:
            # Runs interrupted by a restart are done again
            await s.execute(
                update(Wakeup)
                .where(Wakeup.started_at.is_not(None), Wakeup.finished_at.is_(None))
                .values(started_at=None)
            )
            await s.commit()
        self._loops = [
            asyncio.create_task(self._loop(), name="orchestrator"),
            asyncio.create_task(run_scheduler(), name="scheduler"),
        ]

    async def cancel_runs(self, employee_ids: list[int]) -> None:
        """Stop the runs of these employees now (their project is being deleted)."""
        runs = [self._runs[e] for e in employee_ids if e in self._runs]
        for run in runs:
            run.cancel()
        await asyncio.gather(*runs, return_exceptions=True)

    async def stop(self) -> None:
        tasks = [*self._loops, *self._runs.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                async with SessionLocal() as s:
                    await expand_events(s)
                await self._dispatch()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Orchestrator iteration failed")
            await asyncio.sleep(settings.poll_interval_s)

    async def _dispatch(self) -> None:
        batches: list[tuple[int, int, list[int]]] = []
        async with SessionLocal() as s:
            pending: dict[int, list[Wakeup]] = {}
            now = datetime.now(UTC)
            ready = or_(Wakeup.not_before.is_(None), Wakeup.not_before <= now)
            for w in await s.scalars(select(Wakeup).where(Wakeup.started_at.is_(None), ready).order_by(Wakeup.id)):
                if w.employee_id not in self._runs:
                    pending.setdefault(w.employee_id, []).append(w)
            if not pending:
                return
            accounts = await self._accounts_of(s, list(pending))
            busy: dict[int, int] = {}
            for account in self._run_accounts.values():
                busy[account] = busy.get(account, 0) + 1
            for employee_id, wakeups in pending.items():
                account = accounts.get(employee_id, 1)
                if credits.is_exhausted(account):
                    continue  # Stays queued until the account is back
                if busy.get(account, 0) >= settings.max_concurrent_agents:
                    continue
                busy[account] = busy.get(account, 0) + 1
                # One run per context: every pending reason for the same conversation/task at once
                first = wakeups[0]
                batch = [w for w in wakeups if (w.kind, w.conversation_id, w.task_id) == (first.kind, first.conversation_id, first.task_id)]  # fmt: skip
                for w in batch:
                    w.started_at = now
                batches.append((employee_id, account, [w.id for w in batch]))
            await s.commit()

        for employee_id, account, wakeup_ids in batches:
            run = asyncio.create_task(self._run(employee_id, wakeup_ids), name=f"run-employee-{employee_id}")
            self._runs[employee_id] = run
            self._run_accounts[employee_id] = account
            run.add_done_callback(lambda _, e=employee_id: self._run_done(e))

    def _run_done(self, employee_id: int) -> None:
        self._runs.pop(employee_id, None)
        self._run_accounts.pop(employee_id, None)

    async def _accounts_of(self, s: AsyncSession, employee_ids: list[int]) -> dict[int, int]:
        """Account of each employee, computed over their whole project (spreading)."""
        projects = select(Employee.project_id).where(Employee.id.in_(employee_ids))
        by_project: dict[int, list[Employee]] = {}
        for e in await s.scalars(select(Employee).where(Employee.project_id.in_(projects))):
            by_project.setdefault(e.project_id, []).append(e)
        accounts: dict[int, int] = {}
        for employees in by_project.values():
            accounts |= assign_accounts(employees)
        return accounts

    async def _run(self, employee_id: int, wakeup_ids: list[int]) -> None:
        # Phase 1: prepare (short DB session)
        async with SessionLocal() as s:
            wakeups = list(await s.scalars(select(Wakeup).where(Wakeup.id.in_(wakeup_ids)).order_by(Wakeup.id)))
            employee = await s.get(Employee, employee_id)
            first = wakeups[0]
            run = AgentRun(
                employee_id=employee_id,
                kind=first.kind,
                conversation_id=first.conversation_id,
                task_id=first.task_id,
                reasons=[w.reason for w in wakeups],
                account=self._run_accounts.get(employee_id),
            )
            s.add(run)
            await s.commit()
            run_id = run.id
            try:
                spec, scope = await self._prepare(s, employee, wakeups, run_id)
            except SkipRun as exc:
                await self._finish(s, run_id, wakeup_ids, error=f"skipped: {exc}")
                return
            except Throttled as exc:
                await self._defer(s, run_id, wakeup_ids, exc)
                return
            except (GitHubError, ClaudeRunError) as exc:
                log.error("%s: could not prepare the run: %s", employee.name, exc)
                await self._finish(s, run_id, wakeup_ids, ok=False, error=str(exc))
                return
            except Exception as exc:
                log.exception("%s: could not prepare the run", employee.name)
                await self._finish(s, run_id, wakeup_ids, ok=False, error=repr(exc))
                return

        # Phase 2: run claude (no DB session held for the whole run)
        log.info("%s: %s run started (%s)", employee.name, first.kind, scope)
        result: RunResult | None = None
        error: str | None = None
        try:
            try:
                result = await run_claude(spec)
            except SessionNotFound:
                log.warning("%s: session to resume is gone, starting a new one", employee.name)
                spec.resume_session_id = None
                result = await run_claude(spec)
        except asyncio.CancelledError:
            raise  # Shutdown: the wakeups stay started-but-unfinished and are redone on restart
        except UsageLimitReached as exc:
            await self._requeue(employee_id, run_id, wakeup_ids, exc.limit)
            return
        except ClaudeRunError as exc:
            error = str(exc)
            log.error("%s: run failed: %s", employee.name, exc)
        except Exception as exc:
            error = repr(exc)
            log.exception("%s: run crashed", employee.name)

        # Phase 3: record
        async with SessionLocal() as s:
            if result is not None:
                await self._save_session(s, employee_id, scope, result.session_id, resumed=spec.resume_session_id is not None)
                log.info("%s: run finished (%s turns)", employee.name, result.num_turns)
                if result.is_error:
                    error = result.text or "claude reported an error"
                else:
                    await on_run_succeeded(s, self._run_accounts.get(employee_id, 1))
            await self._finish(s, run_id, wakeup_ids, ok=result is not None and not result.is_error, error=error, result=result)

    async def _defer(self, s: AsyncSession, run_id: int, wakeup_ids: list[int], exc: Throttled) -> None:
        """Throttled: the run is skipped but the wakeups go back in the queue, to be grouped later."""
        run = await s.get(AgentRun, run_id)
        run.finished_at, run.error = datetime.now(UTC), f"skipped: {exc}"
        await s.execute(
            update(Wakeup).where(Wakeup.id.in_(wakeup_ids)).values(started_at=None, not_before=exc.until)
        )
        await s.commit()

    async def _requeue(self, employee_id: int, run_id: int, wakeup_ids: list[int], limit: credits.UsageLimit) -> None:
        """The account is out of credits: the wakeups go back in the queue, the run is not a failure."""
        async with SessionLocal() as s:
            run = await s.get(AgentRun, run_id)
            run.finished_at, run.error = datetime.now(UTC), "skipped: usage limit reached, wakeups queued"
            await s.execute(update(Wakeup).where(Wakeup.id.in_(wakeup_ids)).values(started_at=None))
            await s.commit()
            await on_limit_reached(s, self._run_accounts.get(employee_id, 1), limit)

    async def _finish(
        self,
        s: AsyncSession,
        run_id: int,
        wakeup_ids: list[int],
        *,
        ok: bool | None = None,
        error: str | None = None,
        result: RunResult | None = None,
    ) -> None:
        now = datetime.now(UTC)
        run = await s.get(AgentRun, run_id)
        run.finished_at, run.ok, run.error = now, ok, error
        if result is not None:
            run.claude_session_id, run.num_turns, run.cost_usd = result.session_id, result.num_turns, result.cost_usd
            run.input_tokens, run.output_tokens = result.input_tokens, result.output_tokens
            run.cache_creation_tokens, run.cache_read_tokens = result.cache_creation_tokens, result.cache_read_tokens
        await s.execute(update(Wakeup).where(Wakeup.id.in_(wakeup_ids)).values(finished_at=now))
        await s.commit()
        if ok is False and run.task_id is not None and run.kind == "task":
            await on_task_run_failed(s, run.task_id, error)

    # --- Preparing a run -----------------------------------------------------------

    async def _prepare(
        self, s: AsyncSession, employee: Employee, wakeups: list[Wakeup], run_id: int
    ) -> tuple[RunSpec, str]:
        project = await s.scalar(
            select(Project).where(Project.id == employee.project_id).options(selectinload(Project.employees))
        )
        team = team_of(project)
        member = next(m for m in team.employees if m.name == employee.name)
        system_prompt = "\n\n".join(p for p in [
            render_system_prompt(team, member, services.boss_display_name()),
            RESEARCH_RULES if project.kind == "research" else operating_rules(),
            CHAT_RULES,
            orientation_rule(project.default_branch, await self._is_first_run(s, employee, run_id))
            if project.kind == "company" else None,
            language_rule(services.team_language()),
            version_rule(member.roles),
        ] if p)  # fmt: skip
        oauth_token = token_for(self._run_accounts.get(employee.id) or assign_accounts(project.employees)[employee.id])
        first = wakeups[0]
        rooms = await services.rooms_of(s, employee) if project.kind == "company" else []

        if first.kind == "task":
            task = await s.get(Task, first.task_id)
            await self._check_task(s, project, employee, task, wakeups)
            await self._refresh_repo(project)  # origin/<default branch> up to date for a rebase
            branch, path = await prepare_worktree(project, task)
            task.branch, task.worktree_path, task.status = branch, str(path), TaskStatus.in_progress
            await s.commit()
            scope = f"task:{task.id}"
            spec = RunSpec(
                author_name=employee.name,
                system_prompt=system_prompt + "\n\n" + task_rules(task, project.default_branch),
                prompt=wake_prompt([w.reason for w in wakeups], rooms),
                cwd=path,
                employee_id=employee.id,
                mcp_headers={"X-Palabre-Task": str(task.id)},
                mcp_tools=sorted(mcp_tools_for(employee.permissions, task_run=True)),
                claude_tools=claude_tools_for(employee.permissions),
                model=employee.model,
                effort=effort_for(member.roles),
                oauth_token=oauth_token,
                max_turns=settings.claude_task_max_turns,
            )
        else:
            await self._check_rate(s, project, employee.id, first.conversation_id, run_id, {w.event_type for w in wakeups})
            scope = f"conversation:{first.conversation_id}"
            spec = RunSpec(
                author_name=employee.name,
                system_prompt=system_prompt,
                prompt=wake_prompt([w.reason for w in wakeups], rooms),
                # Their own desk: same directory every time (claude sessions are tied to it)
                cwd=await self._desk(project, employee),
                employee_id=employee.id,
                mcp_headers={"X-Palabre-Conversation": str(first.conversation_id)},
                mcp_tools=sorted(mcp_tools_for(employee.permissions, task_run=False)),
                claude_tools=claude_tools_for(employee.permissions),
                model=employee.model,
                effort=effort_for(member.roles),
                oauth_token=oauth_token,
            )

        await reset_context_if_due(s, employee)  # Before the lookup: no session left to resume
        await reset_session_if_worn(s, employee, scope)
        spec.resume_session_id = await self._session_to_resume(s, employee, scope)
        return spec, scope

    @staticmethod
    async def _session_to_resume(s: AsyncSession, employee: Employee, scope: str) -> str | None:
        if not resumable(scope):
            return None
        return await s.scalar(
            select(AgentSession.claude_session_id).where(AgentSession.employee_id == employee.id, AgentSession.scope == scope)
        )

    async def _desk(self, project: Project, employee: Employee):
        if project.kind == "research":  # No repository: a plain drafts folder
            path = desk_dir(project, employee)
            path.mkdir(parents=True, exist_ok=True)
            return path
        await self._refresh_repo(project)
        return await prepare_desk(project, employee)

    @staticmethod
    async def _is_first_run(s: AsyncSession, employee: Employee, run_id: int) -> bool:
        """The run being prepared is already recorded: it is the first if no earlier one exists."""
        earlier = await s.scalar(
            select(AgentRun.id).where(AgentRun.employee_id == employee.id, AgentRun.id < run_id).limit(1)
        )
        return earlier is None

    async def _refresh_repo(self, project: Project) -> None:
        """Fetch the repository, at most every REPO_SYNC_INTERVAL_S."""
        if time.monotonic() - self._repo_synced_at.get(project.id, float("-inf")) > REPO_SYNC_INTERVAL_S:
            try:
                await sync_repo(project)
                self._repo_synced_at[project.id] = time.monotonic()
            except GitHubError:
                if not (repo_dir(project) / ".git").exists():
                    raise
                log.warning("Project %s: could not refresh the repository, using the last state", project.id)

    async def _check_task(
        self, s: AsyncSession, project: Project, employee: Employee, task: Task | None, wakeups: list[Wakeup]
    ) -> None:
        if task is None or task.assignee_id != employee.id:
            raise SkipRun("the task is no longer assigned to this employee")
        if task.status not in RUNNABLE_TASK_STATUSES:
            raise SkipRun(f"the task is {task.status.value}")
        if task.depends_on:
            statuses = await s.scalars(select(Task.status).where(Task.id.in_(task.depends_on)))
            if any(st != TaskStatus.done for st in statuses):
                raise SkipRun("the task is waiting for other tasks")
        types = {w.event_type for w in wakeups}
        if (
            "changes_requested" in types
            and "task_assigned" not in types
            and task.review_round >= settings.max_review_rounds
        ):
            services.emit_event(
                s, project.id, "review_rounds_exceeded",
                {"task_id": task.id, "rounds": task.review_round, "conversation_id": task.conversation_id},
                role="lead",
            )  # fmt: skip
            await s.commit()
            raise SkipRun(f"{task.review_round} review rounds: the lead has to step in")

    async def _check_rate(
        self, s: AsyncSession, project: Project, employee_id: int, conversation_id: int, run_id: int, event_types: set[str]
    ) -> None:
        """Stops agents that keep pinging each other: runs are counted per employee. Only chatter
        is throttled: workflow events (reviews, merges, bugs, escalations...) always go
        through. Throttled wakeups are not lost: they wait until the window frees up (raises
        Throttled). The boss posting in the conversation lifts it, so does `lift_rate_limit`.
        Skipped wakeups did not run anything: they do not count."""
        if not event_types <= CHATTER_EVENTS:
            return
        since = datetime.now(UTC) - timedelta(hours=1)
        last_boss_message = await s.scalar(
            select(func.max(Message.created_at)).where(
                Message.conversation_id == conversation_id, Message.employee_id.is_(None),
                Message.is_system.is_(False),
            )
        )
        if last_boss_message is not None:
            last_boss_message = last_boss_message if last_boss_message.tzinfo else last_boss_message.replace(tzinfo=UTC)
            since = max(since, last_boss_message)
        last_lift = await s.scalar(
            select(func.max(Event.created_at)).where(
                Event.type == "rate_limit_lifted", Event.payload["conversation_id"].as_integer() == conversation_id
            )
        )
        if last_lift is not None:
            since = max(since, last_lift if last_lift.tzinfo else last_lift.replace(tzinfo=UTC))
        started = list(
            await s.scalars(
                select(AgentRun.started_at)
                .where(
                    AgentRun.employee_id == employee_id,
                    AgentRun.conversation_id.is_not(None),
                    AgentRun.started_at >= since,
                    AgentRun.id != run_id,
                    or_(AgentRun.error.is_(None), AgentRun.error.not_like("skipped%")),
                )
                .order_by(AgentRun.started_at)
            )
        )
        runs = len(started)
        limit = settings.max_runs_per_conversation_hour
        if runs < limit:
            return
        last = self._throttled_at.get((employee_id, conversation_id))
        if last is None or last < since:
            services.emit_event(
                s, project.id, "conversation_throttled", {"conversation_id": conversation_id, "employee_id": employee_id, "runs": runs}, role="lead"
            )
            await s.commit()
            self._throttled_at[(employee_id, conversation_id)] = datetime.now(UTC)
        # A slot frees up when the run that makes us exceed the limit leaves the hour
        if not started or limit <= 0:  # limit 0: nothing ever runs, look again in an hour
            raise Throttled("chatter is disabled", datetime.now(UTC) + timedelta(hours=1))
        frees = started[runs - limit]
        frees = frees if frees.tzinfo else frees.replace(tzinfo=UTC)
        raise Throttled(f"{runs} runs for this employee within an hour", frees + timedelta(hours=1))

    async def lift_rate_limit(self, s: AsyncSession, project_id: int, conversation_id: int) -> None:
        """Restarts the anti-loop window of a conversation: earlier runs no longer count.
        Stored as an already processed event, so it survives a restart."""
        s.add(
            Event(
                project_id=project_id, type="rate_limit_lifted", payload={"conversation_id": conversation_id},
                processed_at=datetime.now(UTC),
            )
        )  # fmt: skip
        await s.commit()
        for key in [k for k in self._throttled_at if k[1] == conversation_id]:
            del self._throttled_at[key]

    async def _save_session(self, s: AsyncSession, employee_id: int, scope: str, session_id: str, resumed: bool) -> None:
        if not resumable(scope):  # Never resumed: nothing worth storing
            return
        session = await s.get(AgentSession, (employee_id, scope))
        if session is None:
            s.add(AgentSession(employee_id=employee_id, scope=scope, claude_session_id=session_id))
        else:
            session.runs = session.runs + 1 if resumed else 1  # Not resumed: a fresh session
            session.claude_session_id = session_id
        await s.commit()


orchestrator = Orchestrator()
