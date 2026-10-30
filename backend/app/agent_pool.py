"""Pool of system users the agents' runs execute as: one user per live run (#152)."""

import asyncio
import contextlib
import grp
import logging
import pwd
from collections import deque
from collections.abc import AsyncIterator

from app.config import settings

log = logging.getLogger(__name__)


def users() -> list[str]:
    """Every account a run may have used: the pool's, then the legacy single agent user."""
    if not settings.agent_user:
        return []
    pool = [f"{settings.agent_user}{i}" for i in range(1, settings.agent_pool_size + 1)]
    return pool + [settings.agent_user]


def check() -> None:
    """At startup: shrinks the pool to the accounts that exist, with a clear error for the first missing one.

    Pool users are numbered, so the pool is the run of accounts present from agent1 on. An account
    needs its user and its private group (the run dir is chowned to it). With no usable account at all
    it raises: falling back to the shared AGENT_USER would undo the isolation of the pool."""
    if not settings.agent_user or settings.agent_pool_size <= 0:
        return
    for size in range(settings.agent_pool_size):
        name = f"{settings.agent_user}{size + 1}"
        try:
            pwd.getpwnam(name)
            grp.getgrnam(name)
        except KeyError:
            log.error(
                "Agent account %s (user and group) does not exist (AGENT_POOL_SIZE=%d): the pool is reduced to %d account(s)",
                name, settings.agent_pool_size, size,
            )  # fmt: skip
            if size == 0:
                raise RuntimeError(
                    f"AGENT_POOL_SIZE={settings.agent_pool_size} but account {name} is missing: "
                    "refusing to run agents on a shared uid (build the image with the pool, or set AGENT_POOL_SIZE=0)"
                ) from None
            settings.agent_pool_size = size
            reset()
            return


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
            log.info("Every agent account has a live run: %d run(s) waiting for one", len(self.waiters))
            try:
                await waiter
            except asyncio.CancelledError:
                # Woken by a release and cancelled right after: pass the free account on
                if waiter.done() and not waiter.cancelled():
                    self._wake_next()
                raise
            finally:
                if waiter in self.waiters:
                    self.waiters.remove(waiter)
        return free.pop(0)

    def release(self, user: str) -> None:
        self._init().append(user)
        self._wake_next()

    def _wake_next(self) -> None:
        while self.waiters:
            waiter = self.waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                break


_pool = _Pool()
# Accounts that still own a clone or cache: they never go back to the pool until restart
_quarantined: set[str] = set()


def quarantine(user: str) -> None:
    """Keeps `user` out of the pool when its lease ends (its clone could not be taken back)."""
    _quarantined.add(user)


def unquarantine(user: str) -> None:
    """Lets `user` go back to the pool: its clone and cache were taken back."""
    _quarantined.discard(user)


def reset() -> None:
    """Forgets the leases (tests, settings changes)."""
    global _pool
    _pool = _Pool()
    _quarantined.clear()


@contextlib.asynccontextmanager
async def lease() -> AsyncIterator[str]:
    """The system user one run executes as; waits if every pool user has a live run.

    Two live runs never share a uid, so neither can read the other's /proc/<pid>/environ.
    Without a pool (pool size 0, or no pool account on this machine) every run uses AGENT_USER; without AGENT_USER, the backend's own user ("")."""
    if not settings.agent_user or settings.agent_pool_size <= 0:
        yield settings.agent_user
        return
    user = await _pool.acquire()
    try:
        yield user
    finally:
        # A process a run left behind (setsid nohup ...) would keep this uid and read the
        # environment of the next run to get it: the account only goes back once it is empty
        if await kill_all(user) and user not in _quarantined:
            _pool.release(user)
        else:
            log.error("Agent account %s still may have processes: removed from the pool until restart", user)


async def kill_all(user: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "-u", user, "/usr/bin/kill", "-KILL", "--", "-1",
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        _, stderr = await asyncio.wait_for(proc.communicate(), 10)
    except (OSError, TimeoutError):
        log.exception("Cannot kill the processes of %s", user)
        return False
    # Nothing left to signal is the normal case: kill then says "No such process"
    return proc.returncode == 0 or b"No such process" in stderr
