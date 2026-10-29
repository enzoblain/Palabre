"""Anti-loop limit: only executed wakeups count, and the boss can lift it."""

from types import SimpleNamespace

import pytest

from app.config import settings
from app.orchestrator.dispatcher import Orchestrator, SkipRun


class RateSession:
    """Answers the two scalar() calls of _check_rate and keeps the count query."""

    def __init__(self, runs: int):
        self.runs = runs
        self.count_query = None

    async def scalar(self, query):
        if self.count_query is None and "max(" in str(query):
            return None  # No boss message
        self.count_query = query
        return self.runs

    async def commit(self):
        pass

    def add(self, _obj):
        pass


def project():
    return SimpleNamespace(id=1)


async def check(orch, s):
    await orch._check_rate(s, project(), 7, 99, {"mention"})


def since_of(query):
    params = query.compile().params
    return next(v for k, v in params.items() if k.startswith("started_at"))


async def test_skipped_wakeups_are_not_counted():
    s = RateSession(0)
    await check(Orchestrator(), s)
    sql = str(s.count_query)
    assert "agent_runs.error IS NULL" in sql
    assert "NOT LIKE" in sql
    assert "skipped%" in s.count_query.compile().params.values()


async def test_limit_reached_skips_the_wakeup():
    with pytest.raises(SkipRun):
        await check(Orchestrator(), RateSession(settings.max_runs_per_conversation_hour))


async def test_lifting_the_limit_moves_the_window_and_lets_a_wakeup_through():
    orch = Orchestrator()
    before = RateSession(0)
    await check(orch, before)
    orch.lift_rate_limit(7)
    after = RateSession(0)
    await check(orch, after)
    assert since_of(after.count_query) > since_of(before.count_query)
    # Runs older than the reset are not counted by the query, so the wakeup passes
    await check(orch, RateSession(0))

