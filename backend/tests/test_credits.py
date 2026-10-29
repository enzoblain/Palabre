"""Claude usage limits: detection, accounts held back, one announcement per episode, resume."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import accounts, credits
from app.credits import FALLBACK_WAIT, UsageLimit, parse_usage_limit
from app.orchestrator import credit_watch

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_state():
    credits.state = credit_watch.credits.state = credits.CreditState()
    yield
    credits.state = credit_watch.credits.state = credits.CreditState()


@pytest.mark.parametrize(
    "text",
    [
        "Claude AI usage limit reached|1793275200",
        "You've hit your limit · resets 3pm (Europe/Paris)",
        "5-hour limit reached ∙ resets 15:20",
        "Credit balance is too low",
    ],
)
def test_limit_detected(text):
    assert parse_usage_limit(text, NOW) is not None


@pytest.mark.parametrize(
    "text", ["", None, "API Error: 429 rate_limit_error", "Overloaded", "Reached max turns (30)", "git push failed"]
)
def test_other_errors_are_not_limits(text):
    assert parse_usage_limit(text, NOW) is None


def test_reset_from_epoch():
    limit = parse_usage_limit("Claude AI usage limit reached|1793275200", NOW)
    assert limit.reset_at == datetime.fromtimestamp(1793275200, UTC) and not limit.estimated


def test_reset_from_clock_with_zone():
    limit = parse_usage_limit("You've hit your limit · resets 3pm (Europe/Paris)", NOW)
    assert limit.reset_at == datetime(2026, 10, 29, 14, 0, tzinfo=UTC)  # CET+1 after DST ended


def test_reset_tomorrow_when_clock_passed():
    limit = parse_usage_limit("usage limit reached, resets 9am (UTC)", NOW)
    assert limit.reset_at == datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


def test_reset_with_date():
    limit = parse_usage_limit("usage limit reached, resets Nov 3, 8am (UTC)", NOW)
    assert limit.reset_at == datetime(2026, 11, 3, 8, 0, tzinfo=UTC)


def test_reset_estimated_when_missing():
    limit = parse_usage_limit("Credit balance is too low", NOW)
    assert limit.estimated and limit.reset_at == NOW + FALLBACK_WAIT


def test_exhausted_until_reset_then_probing():
    credits.state.exhausted[1] = UsageLimit(datetime.now(UTC) + timedelta(hours=1), False)
    assert credits.is_exhausted(1)
    credits.state.exhausted[1] = UsageLimit(datetime.now(UTC) - timedelta(seconds=1), False)
    assert not credits.is_exhausted(1) and credits.state.probing == {1}


def test_automatic_employees_avoid_exhausted_account(monkeypatch):
    monkeypatch.setattr(accounts.settings, "claude_code_oauth_tokens", "a|b")
    team = [SimpleNamespace(id=i, account=None) for i in range(1, 5)]
    credits.state.exhausted[1] = UsageLimit(datetime.now(UTC) + timedelta(hours=1), False)
    assert set(accounts.assign_accounts(team).values()) == {2}
    custom = [SimpleNamespace(id=9, account=1)]
    assert accounts.assign_accounts(custom) == {9: 1}


class AnnounceSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture
def posted(monkeypatch):
    lines, events = [], []

    async def announce(s, text):
        lines.append(text)
        return [(1, 10)]

    monkeypatch.setattr(credit_watch, "_announce", announce)
    return lines, events


async def test_one_announcement_per_episode(posted):
    lines, _ = posted
    s = AnnounceSession()
    at = datetime.now(UTC) + timedelta(hours=1)
    await credit_watch.on_limit_reached(s, 1, UsageLimit(at, False))
    await credit_watch.on_limit_reached(s, 2, UsageLimit(at, False))
    assert len(lines) == 1 and "account 1" in lines[0] and "at " in lines[0]
    assert set(credits.state.exhausted) == {1, 2}


async def test_estimated_reset_is_worded_as_such(posted):
    lines, _ = posted
    await credit_watch.on_limit_reached(AnnounceSession(), 1, UsageLimit(datetime.now(UTC) + timedelta(hours=1), True))
    assert "around" in lines[0]


async def test_resume_after_first_success(posted, monkeypatch):
    lines, _ = posted
    resumed = []

    async def resume(s, since):
        resumed.append(since)

    monkeypatch.setattr(credit_watch, "_resume", resume)
    s = AnnounceSession()
    await credit_watch.on_limit_reached(s, 1, UsageLimit(datetime.now(UTC) + timedelta(hours=1), False))
    await credit_watch.on_run_succeeded(s, 1)
    assert not resumed  # still exhausted: a success elsewhere changes nothing
    credits.state.exhausted[1] = UsageLimit(datetime.now(UTC) - timedelta(seconds=1), False)
    await credit_watch.on_run_succeeded(s, 2)
    assert len(resumed) == 1  # account 1 is released: any success ends the episode
    assert not credits.state.episode
    await credit_watch.on_run_succeeded(s, 1)
    assert len(resumed) == 1  # announced once


async def test_new_episode_announces_again(posted, monkeypatch):
    lines, _ = posted

    async def resume(s, since):
        pass

    monkeypatch.setattr(credit_watch, "_resume", resume)
    s = AnnounceSession()
    for _ in range(2):
        await credit_watch.on_limit_reached(s, 1, UsageLimit(datetime.now(UTC) - timedelta(seconds=1), False))
        await credit_watch.on_run_succeeded(s, 1)
    assert len(lines) == 2


class ResumeSession(AnnounceSession):
    """Serves the queries of `_resume`: open tasks, then the number of queued wakeups."""

    def __init__(self):
        super().__init__()
        self.events = []

    async def execute(self, _query):
        return [(7, "Pause exhausted accounts", SimpleNamespace(value="in_progress"))]

    async def scalar(self, _query):
        return 3

    def add(self, event):
        self.events.append(event)


async def test_resume_wakes_the_lead_with_the_state(posted):
    s = ResumeSession()
    await credit_watch._resume(s, datetime.now(UTC))
    (event,) = s.events
    assert event.type == "credits_back" and event.target_role == "lead"
    assert event.payload["pending"] == 3 and "#7 Pause exhausted accounts (in_progress)" in event.payload["tasks"]
    from app.orchestrator.prompts import reason_for

    reason = reason_for("credits_back", event.payload)
    assert "Queued wakeups: 3" in reason and "?" not in reason.split("Tasks in progress")[0]
