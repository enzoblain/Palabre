"""Claude sessions kept out of the agents' reach: one private store per employee, and a throwaway config dir per run."""

import asyncio
import errno
import logging
import os
import re
import shutil
import stat
import uuid
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

RUN_DIR_MODE = 0o2770
SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


def store_root() -> Path:
    # A variable of its own: the runs receive CLAUDE_CONFIG_DIR, and must never be given the store
    return settings.claude_store_dir or Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def employee_store(employee_id: int) -> Path:
    return store_root() / f"employee-{int(employee_id)}"


# What a run may bring back: a run could otherwise fill the disk through the store
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def _mkdir(path: Path, mode: int) -> None:
    path.mkdir(mode=mode, exist_ok=True)
    os.chmod(path, mode)  # the umask and mkdir's mode would drop the setgid bit


def _copy_fd(src_fd: int, dst: Path, *, file_mode: int, dir_mode: int, names: set[str] | None = None, budget: list[int]) -> None:
    """Copies the regular files and directories of an open directory, walking by file descriptor.

    Every step opens with O_NOFOLLOW relative to its parent and checks the type on the open
    descriptor, so a symlink swapped in by a live run (the directory is writable by every
    agent) is never followed, whenever it is swapped."""
    _mkdir(dst, dir_mode)
    for name in os.listdir(src_fd):
        if names is not None and name not in names:
            continue
        try:
            if stat.S_ISDIR(os.stat(name, dir_fd=src_fd, follow_symlinks=False).st_mode):
                fd = os.open(name, DIR_FLAGS, dir_fd=src_fd)
                try:
                    _copy_fd(fd, dst / name, file_mode=file_mode, dir_mode=dir_mode, budget=budget)
                finally:
                    os.close(fd)
                continue
            fd = os.open(name, FILE_FLAGS, dir_fd=src_fd)
        except OSError as exc:
            # A symlink (ELOOP) or a vanished entry is expected; EACCES means claude wrote a mode we cannot read
            if exc.errno not in (errno.ELOOP, errno.ENOENT, errno.ENOTDIR):
                log.warning("Claude store: cannot read %s: %s", dst / name, exc)
            continue
        with os.fdopen(fd, "rb") as fin:
            info = os.fstat(fin.fileno())
            if not stat.S_ISREG(info.st_mode):
                continue
            if info.st_size > MAX_FILE_BYTES or info.st_size > budget[0]:
                log.warning("Claude store: %s skipped (%d bytes, over the limit)", dst / name, info.st_size)
                continue
            budget[0] -= info.st_size
            tmp = dst / f".{name}.{uuid.uuid4().hex}.tmp"
            with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode), "wb") as fout:
                os.fchmod(fout.fileno(), file_mode)
                # At most the size checked above: a live run may keep appending
                fout.write(fin.read(info.st_size))
            os.replace(tmp, dst / name)  # concurrent runs of one employee: the last writer wins


def _copy_tree(src: Path, dst: Path, *, file_mode: int, dir_mode: int, names: set[str] | None = None) -> None:
    try:
        fd = os.open(src, DIR_FLAGS)
    except OSError:
        return  # missing, or a symlink
    try:
        _copy_fd(fd, dst, file_mode=file_mode, dir_mode=dir_mode, names=names, budget=[MAX_TOTAL_BYTES])
    finally:
        os.close(fd)


def prepare_run_dir(employee_id: int, resume_session_id: str | None) -> Path:
    """A fresh CLAUDE_CONFIG_DIR for one run: no settings, no hooks, only the session to resume.

    The agent user writes in it through group `work` (setgid, like /data/run), and the name is
    unguessable under agent_run_dir, which agents can cross but not list."""
    parent = settings.agent_run_dir
    parent.mkdir(mode=0o711, parents=True, exist_ok=True)
    run_dir = parent / f"claude-{uuid.uuid4().hex}"
    _mkdir(run_dir, RUN_DIR_MODE)
    if resume_session_id and SESSION_ID.fullmatch(resume_session_id):
        projects = employee_store(employee_id) / "projects"
        if projects.is_dir() and not projects.is_symlink():
            wanted = {f"{resume_session_id}.jsonl", resume_session_id}
            _mkdir(run_dir / "projects", RUN_DIR_MODE)
            for project in projects.iterdir():
                if project.is_dir() and not project.is_symlink() and wanted & {c.name for c in project.iterdir()}:
                    _copy_tree(project, run_dir / "projects" / project.name, file_mode=0o660, dir_mode=RUN_DIR_MODE, names=wanted)
    return run_dir


def collect_run_dir(employee_id: int, run_dir: Path) -> bool:
    """Keeps the sessions the run wrote in the employee's store, then deletes the run's config dir.

    Only `projects/` comes back: settings, hooks or anything else the run left there is dropped.
    Returns False if something of the run dir could not be deleted (the caller cleans it as the agent)."""
    try:
        store = employee_store(employee_id)
        store.mkdir(mode=0o700, parents=True, exist_ok=True)
        _copy_tree(run_dir / "projects", store / "projects", file_mode=0o600, dir_mode=0o700)
    except OSError:
        # A full disk must not turn a finished run into a failure that drops its result
        log.exception("Claude sessions of employee %s could not be saved", employee_id)
    finally:
        failed = []
        shutil.rmtree(run_dir, onexc=lambda _f, p, _e: failed.append(p))
    if failed or run_dir.exists():
        log.warning("Claude run dir %s could not be fully deleted (%d entries)", run_dir, len(failed))
        return False
    return True


async def collect(employee_id: int, run_dir: Path) -> None:
    """collect_run_dir, then, if the backend could not delete everything, the agent user empties it."""
    if await asyncio.to_thread(collect_run_dir, employee_id, run_dir) or not settings.agent_user:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "-u", settings.agent_user, "/usr/local/bin/palabre-rm-clone", str(run_dir),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        _, stderr = await proc.communicate()
    except OSError:
        log.exception("Claude run dir %s: cannot start the cleanup as the agent", run_dir)
        return
    await asyncio.to_thread(shutil.rmtree, run_dir, True)
    if proc.returncode or run_dir.exists():
        log.error("Claude run dir %s is still there: %s", run_dir, stderr.decode(errors="replace").strip())


def session_dirs(project_id: int) -> list[Path]:
    """Every employee's session directories of one project (claude names them after the working directory)."""
    prefix = re.sub(r"[^A-Za-z0-9]", "-", str(settings.projects_dir / f"project-{project_id}"))
    root = store_root()
    found = []
    if root.is_dir():
        for store in root.glob("employee-*"):
            projects = store / "projects"
            if projects.is_dir():
                found += [d for d in projects.iterdir() if d.name == prefix or d.name.startswith(prefix + "-")]
        # Sessions of a volume made before the per-employee stores
        legacy = root / "projects"
        if legacy.is_dir():
            found += [d for d in legacy.iterdir() if d.name == prefix or d.name.startswith(prefix + "-")]
    return found
