"""Per-run MCP tokens: one random token per agent run, valid only while that run lives."""

import secrets
from pathlib import Path

# token -> (employee id, config file holding it). In memory on purpose: a restart kills the runs.
_active: dict[str, tuple[int, Path | None]] = {}
# token -> Mcp-Session-Id of the only session allowed to use it (None while it is being opened)
_sessions: dict[str, str | None] = {}
# token -> number of initialize requests seen (the session number in the logs)
_initializes: dict[str, int] = {}


def issue(employee_id: int) -> str:
    token = secrets.token_urlsafe(32)
    _active[token] = (employee_id, None)
    return token


def attach_config(token: str, path: Path) -> None:
    if token in _active:
        _active[token] = (_active[token][0], path)


def employee_of(token: str) -> int | None:
    """Employee behind a live token. The first use proves claude has read its config: delete it."""
    entry = _active.get(token)
    if entry is None:
        return None
    employee_id, path = entry
    if path is not None:
        path.unlink(missing_ok=True)
        _active[token] = (employee_id, None)
    return employee_id


def count_initialize(token: str) -> int:
    """Rank of this initialize among the run's (1 for the first), to see how many sessions claude opens."""
    _initializes[token] = _initializes.get(token, 0) + 1
    return _initializes[token]


def claim_initialize(token: str) -> bool:
    """A token opens one MCP session only: the first initialize claims it, any later one is refused."""
    if token in _sessions:
        return False
    _sessions[token] = None
    return True


def bind_session(token: str, session_id: str) -> None:
    if token in _sessions:
        _sessions[token] = session_id


def release_claim(token: str) -> None:
    """The claiming initialize failed, so no session exists: let the run retry."""
    if _sessions.get(token, "") is None:
        del _sessions[token]


def session_allowed(token: str, session_id: str) -> bool:
    return _sessions.get(token) == session_id


def revoke(token: str) -> None:
    _active.pop(token, None)
    _sessions.pop(token, None)
    _initializes.pop(token, None)
