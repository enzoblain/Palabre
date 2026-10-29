"""Claude usage limits: spotting them in a run's output and remembering which accounts are exhausted."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

# Wait before trying an account again when the output gives no reset time
FALLBACK_WAIT = timedelta(minutes=30)

# Wording of the limit messages of `claude -p`. A plain rate limit (429), an overload or a
# crash must not match: they pass by themselves and do not call for a pause.
LIMIT_RE = re.compile(
    r"(usage|session|weekly|opus|sonnet|\d+-hour)\s+limit\s+(reached|hit|exceeded)"
    r"|(hit|reached|exceeded)\s+your\s+(\w+\s+)?limit"
    r"|credit balance is too low"
    r"|out of (extra usage|credits)",
    re.IGNORECASE,
)
EPOCH_RE = re.compile(r"limit[^|]*\|\s*(\d{9,11})\b", re.IGNORECASE)
RESET_RE = re.compile(
    r"resets?\s+(?:at\s+)?(?:(?P<month>[A-Za-z]{3})[a-z]*\s+(?P<day>\d{1,2}),?\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?(?:\s*\((?P<tz>[\w/+-]+)\))?",
    re.IGNORECASE,
)  # fmt: skip


@dataclass
class UsageLimit:
    reset_at: datetime
    estimated: bool  # the output gave no usable reset time


def parse_usage_limit(text: str | None, now: datetime | None = None) -> UsageLimit | None:
    """The limit a run hit, from its error text (None if it is another error)."""
    if not text or not LIMIT_RE.search(text):
        return None
    now = now or datetime.now(UTC)
    if m := EPOCH_RE.search(text):
        return UsageLimit(datetime.fromtimestamp(int(m.group(1)), UTC), False)
    reset = _parse_reset(text, now)
    return UsageLimit(reset, False) if reset else UsageLimit(now + FALLBACK_WAIT, True)


def _parse_reset(text: str, now: datetime) -> datetime | None:
    m = RESET_RE.search(text)
    if not m:
        return None
    try:
        tz = ZoneInfo(m["tz"]) if m["tz"] else now.astimezone().tzinfo
        hour, minute = int(m["hour"]), int(m["minute"] or 0)
        if m["ampm"]:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if m["ampm"].lower() == "pm" else 0)
        local = now.astimezone(tz)
        at = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if m["month"]:
            month = datetime.strptime(m["month"].title(), "%b").month
            at = at.replace(month=month, day=int(m["day"]))
            if at <= local:
                at = at.replace(year=at.year + 1)
        elif at <= local:
            at += timedelta(days=1)
    except (ValueError, KeyError):
        return None
    return at.astimezone(UTC)


@dataclass
class CreditState:
    """In memory: after a restart the first run that hits the limit rebuilds it."""

    exhausted: dict[int, UsageLimit] = field(default_factory=dict)  # account → limit it hit
    probing: set[int] = field(default_factory=set)  # reset passed, waiting for a run to succeed
    episode: bool = False  # Enzo was told, and has not been told it is over
    since: datetime | None = None


state = CreditState()


def is_exhausted(account: int, now: datetime | None = None) -> bool:
    """Whether the account must not run. Once its reset time has passed it is released
    (and probed: the next run that succeeds ends the episode). The release lives in this check
    so that the dispatcher, the account spreading and the status API all see the same state."""
    limit = state.exhausted.get(account)
    if limit is None:
        return False
    if limit.reset_at <= (now or datetime.now(UTC)):
        del state.exhausted[account]
        state.probing.add(account)
        return False
    return True


def exhausted_accounts() -> list[int]:
    return sorted(a for a in list(state.exhausted) if is_exhausted(a))
