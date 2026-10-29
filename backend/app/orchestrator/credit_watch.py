"""When Claude credits run out: tell the boss once, hold the wakeups, wake the lead on return."""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import credits
from app.credits import UsageLimit
from app.models import Employee, Project, Task, TaskStatus, Wakeup
from app.services import direction_conversation_id, emit_event, post_system_message

log = logging.getLogger(__name__)

OPEN_STATUSES = [s for s in TaskStatus if s not in (TaskStatus.done, TaskStatus.cancelled)]


def _clock(at: datetime) -> str:
    return at.astimezone().strftime("%H:%M")


async def _announce(s: AsyncSession, text: str) -> list[tuple[int, int]]:
    """The line in every project's direction channel: (project id, conversation id)."""
    posted = []
    for project_id in list(await s.scalars(select(Project.id))):
        if (conversation_id := await direction_conversation_id(s, project_id)) is not None:
            await post_system_message(s, conversation_id, text)
            posted.append((project_id, conversation_id))
    return posted


async def on_limit_reached(s: AsyncSession, account: int, limit: UsageLimit) -> None:
    """A run hit the limit: the account rests until its reset. The boss hears of it once per episode."""
    state = credits.state
    state.exhausted[account] = limit
    state.probing.discard(account)
    log.warning("Claude account %s is exhausted until %s", account, limit.reset_at.isoformat())
    if state.episode:
        return
    state.episode, state.since = True, datetime.now(UTC)
    when = ("around " if limit.estimated else "at ") + _clock(limit.reset_at)
    await _announce(s, f"Claude credits exhausted on account {account}, work resumes {when}. Wakeups are queued, nothing is lost.")
    await s.commit()


async def on_run_succeeded(s: AsyncSession, account: int) -> None:
    """A run went through: if every account that rested has worked again, the episode is over."""
    state = credits.state
    if not state.episode:
        return
    credits.exhausted_accounts()  # releases the accounts whose reset has passed
    state.probing.discard(account)
    if state.exhausted or state.probing:
        return
    since, state.episode, state.since = state.since, False, None
    await _resume(s, since)


async def _resume(s: AsyncSession, since: datetime | None) -> None:
    log.info("Claude credits are back")
    for project_id, conversation_id in await _announce(s, "Claude credits are back, the team resumes. The lead is catching up on the queue."):
        tasks = await s.execute(
            select(Task.id, Task.title, Task.status).where(Task.project_id == project_id, Task.status.in_(OPEN_STATUSES)).order_by(Task.id)
        )
        pending = await s.scalar(
            select(func.count())
            .select_from(Wakeup)
            .join(Employee, Employee.id == Wakeup.employee_id)
            .where(Employee.project_id == project_id, Wakeup.started_at.is_(None))
        )
        listing = "; ".join(f"#{i} {title} ({status.value})" for i, title, status in tasks) or "none"
        emit_event(
            s, project_id, "credits_back",
            {"conversation_id": conversation_id, "since": _clock(since) if since else "?", "tasks": listing, "pending": pending},
            role="lead",
        )  # fmt: skip
    await s.commit()
