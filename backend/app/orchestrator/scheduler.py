"""Company rituals: the daily stand-up, the scribe once a conversation goes quiet, and
retries of task runs that failed."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Event, Message, Project, Room
from app.orchestrator.retries import retry_failed_tasks
from app.services import emit_event

log = logging.getLogger(__name__)

INTERVAL_S = 30
# The daily only happens within this window after DAILY_TIME (not at 11 pm after a restart)
DAILY_WINDOW = timedelta(hours=1)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def run_scheduler() -> None:
    while True:
        try:
            async with SessionLocal() as s:
                await _daily(s)
                await _idle_conversations(s)
                await retry_failed_tasks(s)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Scheduler iteration failed")
        await asyncio.sleep(INTERVAL_S)


async def _daily(s: AsyncSession) -> None:
    if not settings.daily_time:
        return
    now = datetime.now().astimezone()  # Local time of the container (TZ)
    hour, minute = map(int, settings.daily_time.split(":"))
    daily_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now.weekday() >= 5 or not daily_at <= now < daily_at + DAILY_WINDOW:
        return
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for project_id in list(await s.scalars(select(Project.id))):
        done_today = await s.scalar(
            select(Event.id)
            .where(Event.project_id == project_id, Event.type == "daily", Event.created_at >= start_of_day)
            .limit(1)
        )
        if done_today is None:
            emit_event(s, project_id, "daily")
    await s.commit()


async def _idle_conversations(s: AsyncSession) -> None:
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.idle_minutes)
    rows = await s.execute(
        select(Conversation, Room.project_id, func.max(Message.id), func.max(Message.created_at))
        .join(Message, Message.conversation_id == Conversation.id)
        .join(Room, Room.id == Conversation.room_id)
        .group_by(Conversation.id, Room.project_id)
    )
    for conversation, project_id, last_id, last_at in rows:
        if last_id > conversation.idle_notified_message_id and _aware(last_at) < cutoff:
            emit_event(s, project_id, "conversation_idle", {"conversation_id": conversation.id})
            conversation.idle_notified_message_id = last_id
    await s.commit()
