"""Per-run MCP tokens: one random token per agent run, valid only while that run lives."""

import secrets
from pathlib import Path

# token -> (employee id, config file holding it). In memory on purpose: a restart kills the runs.
_active: dict[str, tuple[int, Path | None]] = {}


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


def revoke(token: str) -> None:
    _active.pop(token, None)
