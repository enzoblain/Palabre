"""Context reset every N finished tasks: counter, threshold, off at 0, what is kept."""

from types import SimpleNamespace

import pytest

from app.config import settings
from app.orchestrator import context_reset


class FakeDb:
    """Counts the finished tasks it is told about; records deletions and commits."""

    def __init__(self, finished: int):
        self.finished, self.executed, self.commits = finished, [], 0

    async def scalar(self, _query):
        return self.finished

    async def execute(self, query):
        self.executed.append(str(query))

    async def commit(self):
        self.commits += 1


def employee():
    return SimpleNamespace(id=1, name="Malik", context_reset_at=None, created_at=None)


@pytest.fixture(autouse=True)
def every_five(monkeypatch):
    monkeypatch.setattr(settings, "context_reset_every_tasks", 5)


async def test_counter_is_read_from_the_database():
    assert await context_reset.finished_tasks_since_reset(FakeDb(3), employee()) == 3


async def test_below_threshold_nothing_happens():
    s, who = FakeDb(4), employee()
    assert not await context_reset.reset_context_if_due(s, who)
    assert s.executed == [] and who.context_reset_at is None


@pytest.mark.parametrize("finished", [5, 7])
async def test_at_threshold_sessions_are_deleted_and_counter_restarts(finished):
    s, who = FakeDb(finished), employee()
    assert await context_reset.reset_context_if_due(s, who)
    assert len(s.executed) == 1 and s.executed[0].startswith("DELETE FROM agent_sessions")
    assert who.context_reset_at is not None and s.commits == 1


async def test_only_agent_sessions_are_deleted():
    s = FakeDb(5)
    await context_reset.reset_context_if_due(s, employee())
    assert [q for q in s.executed if "notes" in q or "tasks" in q or "messages" in q] == []


async def test_zero_disables_the_reset(monkeypatch):
    monkeypatch.setattr(settings, "context_reset_every_tasks", 0)
    s, who = FakeDb(50), employee()
    assert not await context_reset.reset_context_if_due(s, who)
    assert s.executed == [] and who.context_reset_at is None
