"""Real quota usage of each Claude account, read from the OAuth usage endpoint behind Claude Code's /usage."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.accounts import account_count, token_for

log = logging.getLogger(__name__)

# DEBUG traces of these libraries can include request/response headers, hence the bearer token
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TIMEOUT = 10
CACHE_TTL = 60

SESSION_KEY = "five_hour"
WEEK_KEY = "seven_day"
MODEL_PREFIX = "seven_day_"
# Explicit list: the API also has seven_day_oauth_apps and may gain other non-model keys
MODELS = ("opus", "sonnet")


@dataclass
class Window:
    used_percent: float
    resets_at: datetime | None


@dataclass
class AccountUsage:
    account: int
    error: str | None = None
    session: Window | None = None
    week: Window | None = None
    models: dict[str, Window] = field(default_factory=dict)


# account number → (monotonic time, result); errors are cached too so a dead account is not hammered
_cache: dict[int, tuple[float, AccountUsage]] = {}
# One lock per account so concurrent refreshes make a single call to the endpoint
_locks: dict[int, asyncio.Lock] = {}


def _window(raw: object) -> Window | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("utilization"), int | float):
        return None
    resets = raw.get("resets_at")
    try:
        resets_at = datetime.fromisoformat(resets) if isinstance(resets, str) else None
    except ValueError:
        resets_at = None
    return Window(used_percent=float(raw["utilization"]), resets_at=resets_at)


def parse(account: int, data: object) -> AccountUsage:
    """Turn the endpoint's JSON into windows; unknown or null windows are left out."""
    if not isinstance(data, dict):
        return AccountUsage(account, error="Unexpected response from the usage API")
    models = {
        model: w for model in MODELS if (w := _window(data.get(MODEL_PREFIX + model)))
    }
    return AccountUsage(
        account, session=_window(data.get(SESSION_KEY)), week=_window(data.get(WEEK_KEY)), models=models
    )


async def _fetch(client: httpx.AsyncClient, account: int) -> AccountUsage:
    token = token_for(account)
    if not token:
        return AccountUsage(account, error="No token for this account")
    headers = {"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"}
    try:
        resp = await client.get(USAGE_URL, headers=headers)
        resp.raise_for_status()
        return parse(account, resp.json())
    except httpx.HTTPStatusError as exc:
        # Status only: never log the request, it carries the token
        log.warning("Usage API answered %s for account %s", exc.response.status_code, account)
        return AccountUsage(account, error=f"Usage API answered HTTP {exc.response.status_code}")
    except httpx.TimeoutException:
        log.warning("Usage API timed out for account %s", account)
        return AccountUsage(account, error="Usage API timed out")
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Usage API failed for account %s (%s)", account, type(exc).__name__)
        return AccountUsage(account, error="Usage API unreachable or returned invalid data")


async def fetch_all() -> list[AccountUsage]:
    """Usage of every configured account, cached for a minute. One failing account does not affect the others."""
    accounts = range(1, account_count() + 1)

    async def one(client: httpx.AsyncClient, account: int) -> AccountUsage:
        async with _locks.setdefault(account, asyncio.Lock()):
            # Checked under the lock: a concurrent caller may have just filled the cache
            cached = _cache.get(account)
            if cached and time.monotonic() - cached[0] < CACHE_TTL:
                return cached[1]
            result = await _fetch(client, account)
            _cache[account] = (time.monotonic(), result)
            return result

    # In parallel: dead accounts must not add up their timeouts
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return list(await asyncio.gather(*(one(client, a) for a in accounts)))
