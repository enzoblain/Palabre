"""Pool of system users the agents' runs execute as: one user per live run (#152)."""

import asyncio
import contextlib
from collections import deque
from collections.abc import AsyncIterator

from app.config import settings


def users() -> list[str]:
    """Every account a run may have used: the pool's, then the legacy single agent user."""
    if not settings.agent_user:
        return []
    pool = [f"{settings.agent_user}{i}" for i in range(1, settings.agent_pool_size + 1)]
    return pool + [settings.agent_user]


class _Pool:
    def __init__(self) -> None:
        self.free: list[str] | None = None
        self.waiters: deque[asyncio.Future[None]] = deque()

    def _init(self) -> list[str]:
        if self.free is None:
            self.free = users()[: settings.agent_pool_size]
        return self.free

    async def acquire(self) -> str:
        free = self._init()
        while not free:
            waiter = asyncio.get_running_loop().create_future()
            self.waiters.append(waiter)
            try:
                await waiter
            finally:
                if waiter in self.waiters:
                    self.waiters.remove(waiter)
        return free.pop(0)

    def release(self, user: str) -> None:
        self._init().append(user)
        while self.waiters:
            waiter = self.waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                break


_pool = _Pool()


def reset() -> None:
    """Forgets the leases (tests, settings changes)."""
    global _pool
    _pool = _Pool()


@contextlib.asynccontextmanager
async def lease() -> AsyncIterator[str]:
    """The system user one run executes as; waits if every pool user has a live run.

    Two live runs never share a uid, so neither can read the other's /proc/<pid>/environ.
    Without a pool (pool size 0) every run uses AGENT_USER; without AGENT_USER, the backend's own user ("")."""
    if not settings.agent_user or settings.agent_pool_size <= 0:
        yield settings.agent_user
        return
    user = await _pool.acquire()
    try:
        yield user
    finally:
        _pool.release(user)
