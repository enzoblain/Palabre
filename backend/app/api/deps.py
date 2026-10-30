"""Shared FastAPI dependencies: authentication and lookups."""

import logging
import secrets
import time
from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import Base, get_session

log = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ModelT = TypeVar("ModelT", bound=Base)


# Failed authentications per client IP (monotonic timestamps), in memory: a restart resets it.
# Behind the frontend's nginx every browser shares the proxy's IP, hence one bucket.
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


async def require_admin(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = _recent_failures(ip, now)
    if len(recent) >= settings.auth_max_failures:
        retry = max(1, int(settings.auth_fail_window_seconds - (now - recent[0])) + 1)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed authentications", headers={"Retry-After": str(retry)})
    if cred is None or not secrets.compare_digest(cred.credentials.encode(), settings.admin_token.encode()):
        if len(_failures) > _SWEEP_ABOVE:
            for known in list(_failures):
                _recent_failures(known, now)
        recent = _failures.setdefault(ip, [])
        recent.append(now)
        if len(recent) == settings.auth_max_failures:
            log.warning("API auth: %s locked out after %d failed attempts", ip, len(recent))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


async def get_or_404(s: AsyncSession, model: type[ModelT], id: int, **kwargs) -> ModelT:
    obj = await s.get(model, id, **kwargs)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} {id} not found")
    return obj
