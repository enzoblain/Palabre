"""Real quota usage of each Claude account, read from the OAuth usage endpoint behind Claude Code's /usage."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.accounts import account_count, token_for
from app.config import settings

log = logging.getLogger(__name__)

# DEBUG traces of these libraries can include request/response headers, hence the bearer token
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
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


def _header_window(headers: httpx.Headers, name: str) -> Window | None:
    """One window from the unified rate-limit headers: utilization is a 0-1 fraction, reset is epoch seconds."""
    try:
        used = float(headers[f"anthropic-ratelimit-unified-{name}-utilization"])
    except (KeyError, ValueError):
        return None
    try:
        resets_at = datetime.fromtimestamp(float(headers[f"anthropic-ratelimit-unified-{name}-reset"]), UTC)
    except (KeyError, ValueError, OverflowError, OSError):
        resets_at = None
    return Window(used_percent=used * 100, resets_at=resets_at)


async def _probe(client: httpx.AsyncClient, account: int, headers: dict[str, str]) -> AccountUsage | None:
    """Fallback for tokens from `claude setup-token`, which only have the inference scope and are refused by the
    usage endpoint: a 1-token message carries the same 5h and week figures in its response headers."""
    body = {"model": settings.quota_probe_model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
    resp = await client.post(MESSAGES_URL, headers={**headers, "anthropic-version": "2023-06-01"}, json=body)
    session = _header_window(resp.headers, "5h")
    week = _header_window(resp.headers, "7d")
    if not (session or week):
        log.warning("Rate-limit probe answered %s without usage headers for account %s", resp.status_code, account)
        return None
    return AccountUsage(account, session=session, week=week)


def _http_error(status: int, body: object) -> str:
    """Readable reason for a refused call; only the API's own error message is kept, never the request."""
    message = ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        message = str(body["error"].get("message") or "")[:200]
    if status == 401:
        return "Token rejected (expired or revoked): run `claude setup-token` again" + (f" ({message})" if message else "")
    if status == 403:
        return (
            "This token cannot read usage (tokens from `claude setup-token` lack the user:profile scope): "
            "use a token with that scope, e.g. from `claude login`" + (f" [{message}]" if message else "")
        )
    if status == 429:
        return "Usage API rate-limited, retry in a minute"
    return f"Usage API answered HTTP {status}" + (f" ({message})" if message else "")


async def _fetch(client: httpx.AsyncClient, account: int) -> AccountUsage:
    token = token_for(account)
    if not token:
        return AccountUsage(account, error="No token for this account")
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "palabre",
    }
    try:
        resp = await client.get(USAGE_URL, headers=headers)
        if resp.status_code in (401, 403):
            # Not necessarily dead: setup-token tokens lack the profile scope the usage endpoint wants
            probed = await _probe(client, account, headers) if settings.quota_probe_enabled else None
            if probed:
                return probed
        resp.raise_for_status()
        return parse(account, resp.json())
    except httpx.HTTPStatusError as exc:
        # Status only: never log the request, it carries the token
        status = exc.response.status_code
        log.warning("Usage API answered %s for account %s", status, account)
        try:
            body = exc.response.json()
        except ValueError:
            body = None
        return AccountUsage(account, error=_http_error(status, body))
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
