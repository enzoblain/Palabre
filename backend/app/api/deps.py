"""Shared FastAPI dependencies: authentication and lookups."""

import asyncio
import logging
import secrets
import socket
import time
from typing import Annotated, TypeVar

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import NOT_FOUND, ApiError, ErrorCode
from app.config import settings
from app.db import Base, get_session

log = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ModelT = TypeVar("ModelT", bound=Base)


# Failed authentications per client IP (monotonic timestamps), in memory: a restart resets it.
# Behind the frontend's nginx the client is read from X-Real-IP, but only when the request comes from that proxy.
_failures: dict[str, list[float]] = {}
# Past this many tracked IPs, expired entries are swept (many source addresses must not grow it forever)
_SWEEP_ABOVE = 1024


def _recent_failures(ip: str, now: float) -> list[float]:
    recent = [t for t in _failures.get(ip, []) if now - t < settings.auth_fail_window_seconds]
    if recent:
        _failures[ip] = recent
    else:
        _failures.pop(ip, None)
    return recent


_PROXY_TTL = 30.0
_proxy_cache: tuple[float, set[str]] = (float("-inf"), set())


async def _trusted_proxy_ips() -> set[str]:
    """Addresses of the trusted proxy hosts, resolved again every few seconds (a container's IP changes on restart)."""
    global _proxy_cache
    now = time.monotonic()
    if now - _proxy_cache[0] < _PROXY_TTL:
        return _proxy_cache[1]
    ips: set[str] = set()
    loop = asyncio.get_running_loop()
    for host in settings.trusted_proxy_hosts:
        try:
            ips.update(info[4][0] for info in await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM))
        except OSError:
            pass
    _proxy_cache = (now, ips)
    return ips


async def client_ip(request: Request) -> str:
    """The caller's IP; X-Real-IP (set by nginx to its $remote_addr) counts only from a trusted proxy, never from a direct caller."""
    peer = request.client.host if request.client else "unknown"
    real = request.headers.get("x-real-ip", "").strip()
    if real and peer in await _trusted_proxy_ips():
        return real
    return peer


async def require_admin(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    ip = await client_ip(request)
    now = time.monotonic()
    recent = _recent_failures(ip, now)
    if len(recent) >= settings.auth_max_failures:
        retry = max(1, int(settings.auth_fail_window_seconds - (now - recent[0])) + 1)
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ErrorCode.AUTH_LOCKED,
            "Too many failed authentications",
            headers={"Retry-After": str(retry)},
        )
    if cred is None or not secrets.compare_digest(cred.credentials.encode(), settings.admin_token.encode()):
        if len(_failures) > _SWEEP_ABOVE:
            for known in list(_failures):
                _recent_failures(known, now)
        recent = _failures.setdefault(ip, [])
        recent.append(now)
        if len(recent) == settings.auth_max_failures:
            log.warning("API auth: %s locked out after %d failed attempts", ip, len(recent))
        raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.AUTH_INVALID_TOKEN, "Invalid token")


async def get_or_404(s: AsyncSession, model: type[ModelT], id: int, **kwargs) -> ModelT:
    obj = await s.get(model, id, **kwargs)
    if obj is None:
        code = NOT_FOUND.get(model.__name__, ErrorCode.NOT_FOUND)
        raise ApiError(status.HTTP_404_NOT_FOUND, code, f"{model.__name__} {id} not found")
    return obj
