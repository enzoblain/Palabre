"""Claude sessions kept out of the agents' reach: one private store per employee, and a throwaway config dir per run."""

import os
import re
import shutil
import uuid
from pathlib import Path

from app.config import settings

SESSION_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


def store_root() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def employee_store(employee_id: int) -> Path:
    return store_root() / f"employee-{int(employee_id)}"


def _copy_tree(src: Path, dst: Path, *, file_mode: int, dir_mode: int) -> None:
    """Copies regular files and directories only: a symlink planted by an agent is never followed."""
    if src.is_symlink() or not src.is_dir():
        return
    dst.mkdir(mode=dir_mode, parents=True, exist_ok=True)
    os.chmod(dst, dir_mode)
    for entry in os.scandir(src):
        target = dst / entry.name
        if entry.is_symlink():
            continue
        if entry.is_dir(follow_symlinks=False):
            _copy_tree(Path(entry.path), target, file_mode=file_mode, dir_mode=dir_mode)
        elif entry.is_file(follow_symlinks=False):
            tmp = target.with_name(f".{entry.name}.{uuid.uuid4().hex}.tmp")
            with open(entry.path, "rb") as fin, open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode), "wb") as fout:
                shutil.copyfileobj(fin, fout)
            os.replace(tmp, target)


def prepare_run_dir(employee_id: int, resume_session_id: str | None) -> Path:
    """A fresh CLAUDE_CONFIG_DIR for one run: no settings, no hooks, only the session to resume.

    The agent user needs to write in it (group `work`), and the directory name is unguessable
    under agent_run_dir, which agents can cross but not list."""
    parent = settings.agent_run_dir
    parent.mkdir(mode=0o711, parents=True, exist_ok=True)
    run_dir = parent / f"claude-{uuid.uuid4().hex}"
    run_dir.mkdir(mode=0o770)
    os.chmod(run_dir, 0o770)
    if resume_session_id and SESSION_ID.fullmatch(resume_session_id):
        projects = employee_store(employee_id) / "projects"
        if projects.is_dir() and not projects.is_symlink():
            for project in projects.iterdir():
                if project.is_symlink() or not project.is_dir():
                    continue
                dest = run_dir / "projects" / project.name
                for name in (f"{resume_session_id}.jsonl", resume_session_id):
                    source = project / name
                    if source.is_symlink():
                        continue
                    if source.is_dir():
                        _copy_tree(source, dest / name, file_mode=0o660, dir_mode=0o770)
                    elif source.is_file():
                        dest.mkdir(mode=0o770, parents=True, exist_ok=True)
                        os.chmod(dest, 0o770)
                        shutil.copyfile(source, dest / name)
                        os.chmod(dest / name, 0o660)
    return run_dir


def collect_run_dir(employee_id: int, run_dir: Path) -> None:
    """Keeps the sessions the run wrote in the employee's store, then deletes the run's config dir.

    Only `projects/` comes back: settings, hooks or anything else the run left there is dropped."""
    try:
        store = employee_store(employee_id)
        store.mkdir(mode=0o700, parents=True, exist_ok=True)
        _copy_tree(run_dir / "projects", store / "projects", file_mode=0o600, dir_mode=0o700)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


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
