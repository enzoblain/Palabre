"""The scribe is woken only after a quiet spell and enough new messages."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.orchestrator import scheduler


class RowsSession:
    def __init__(self, rows):
        self.rows = rows
        self.events = []

    async def execute(self, _query):
        return self.rows

    async def commit(self):
        pass


def row(new_messages, quiet_minutes, notified=0, last_id=100):
    conversation = SimpleNamespace(id=1, idle_notified_message_id=notified)
    last_at = datetime.now(UTC) - timedelta(minutes=quiet_minutes)
    return conversation, 7, last_id, last_at, new_messages


@pytest.fixture
def emitted(monkeypatch):
    events = []
    monkeypatch.setattr(scheduler, "emit_event", lambda _s, project_id, type, payload: events.append((project_id, type, payload)))
    return events


def test_defaults():
    assert settings.idle_minutes == 30
    assert settings.idle_min_messages == 5


@pytest.mark.parametrize(
    "new_messages, quiet_minutes, woken",
    [(5, 31, True), (12, 31, True), (4, 31, False), (1, 31, False), (5, 29, False)],
)
async def test_idle_needs_quiet_and_enough_messages(emitted, new_messages, quiet_minutes, woken):
    rows = [row(new_messages, quiet_minutes)]
    conversation = rows[0][0]
    await scheduler._idle_conversations(RowsSession(rows))
    assert emitted == ([(7, "conversation_idle", {"conversation_id": 1})] if woken else [])
    assert conversation.idle_notified_message_id == (100 if woken else 0)


async def test_threshold_is_configurable(emitted, monkeypatch):
    monkeypatch.setattr(settings, "idle_min_messages", 2)
    await scheduler._idle_conversations(RowsSession([row(2, 31)]))
    assert len(emitted) == 1


@pytest.mark.parametrize("name", ["IDLE_MINUTES", "IDLE_MIN_MESSAGES"])
@pytest.mark.parametrize("value", ["0", "-3"])
def test_idle_settings_reject_below_one(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()
