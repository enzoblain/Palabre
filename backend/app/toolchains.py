"""Toolchains the agents install for the whole team (install_toolchain), without root.

They live in the /data volume, so they survive restarts and image rebuilds, and their
commands are linked into one directory added to every agent's PATH. Archives come from
the official download sites only, and are checked against their published SHA-256.
"""

import asyncio
import hashlib
import platform
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path

import httpx

from app.config import settings
from app.errors import WorkflowError

TOOLCHAINS = {
    "node": 'Node.js with npm and npx. Version: "lts" (default), "latest", a major ("20") or exact ("20.11.1")',
    "go": 'Go. Version: "stable" (default), a minor ("1.22") or exact ("1.22.3")',
    "python": "A shared Python venv (python, pip, installed commands such as pytest). Packages: names with optional pins",
}
VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,30}$")
# "name", "name[extra]", "name==1.2": no option, URL or path, so pip only reads PyPI names
PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}(\[[A-Za-z0-9,._-]{1,60}\])?((==|>=|<=|~=|!=|<|>)[A-Za-z0-9.*+!_-]{1,30})?$")
_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def bin_dir() -> Path:
    return settings.toolchains_dir / "bin"


def gopath(employee_id: int) -> Path:
    """The employee's own Go cache: its code is executed by the runs, so no other employee writes in it."""
    return settings.toolchains_dir / "gopath" / f"employee-{employee_id}"


def agent_env(employee_id: int) -> dict[str, str]:
    """Variables the agents' commands need to use the installed toolchains."""
    return {
        "GOPATH": str(gopath(employee_id)),
        "GOMODCACHE": str(gopath(employee_id) / "pkg" / "mod"),
        # No C compiler in the image: pure Go builds
        "CGO_ENABLED": "0",
    }


def installed() -> dict[str, str]:
    """Command → the file it runs, for what is currently linked."""
    if not bin_dir().is_dir():
        return {}
    return {p.name: str(p.resolve()) for p in sorted(bin_dir().iterdir()) if p.is_symlink() or p.is_file()}


async def install(name: str, version: str = "", packages: str = "") -> str:
    if name not in TOOLCHAINS:
        raise WorkflowError(f"Unknown toolchain {name!r}: {', '.join(TOOLCHAINS)}")
    if version and not VERSION_RE.match(version):
        raise WorkflowError(f"Invalid version: {version!r}")
    async with _locks[name]:
        try:
            if name == "python":
                if version:
                    raise WorkflowError("The python toolchain takes no version: list `packages` instead")
                return await _install_python(packages.replace(",", " ").split())
            if name == "node":
                return await _install_node(version or "lts")
            return await _install_go(version or "stable")
        except httpx.HTTPError as exc:
            raise WorkflowError(f"Download failed: {exc}") from exc


# --- Node.js -------------------------------------------------------------------------


async def _install_node(selector: str) -> str:
    arch = {"x86_64": "x64", "aarch64": "arm64"}.get(platform.machine())
    if arch is None:
        raise WorkflowError(f"No Node.js build for this machine ({platform.machine()})")
    releases = await _get_json("https://nodejs.org/dist/index.json")
    release = next((r for r in releases if _node_matches(r, selector)), None)
    if release is None:
        raise WorkflowError(f"No Node.js release matches {selector!r}")
    version = release["version"]  # e.g. v20.11.1
    archive = f"node-{version}-linux-{arch}"
    target = settings.toolchains_dir / archive
    if not (target / "bin" / "node").exists():
        sums = await _get_text(f"https://nodejs.org/dist/{version}/SHASUMS256.txt")
        sha = next((line.split()[0] for line in sums.splitlines() if line.endswith(f"{archive}.tar.xz")), None)
        if sha is None:
            raise WorkflowError(f"No checksum published for {archive}")
        await _download_and_extract(f"https://nodejs.org/dist/{version}/{archive}.tar.xz", sha, settings.toolchains_dir)
    _link(target / "bin", ["node", "npm", "npx", "corepack"])
    return f"Node.js {version} installed for the whole team (node, npm, npx)."


def _node_matches(release: dict, selector: str) -> bool:
    version = release["version"].lstrip("v")
    if selector == "lts":
        return bool(release.get("lts"))
    if selector == "latest":
        return True
    return version == selector or version.startswith(selector.lstrip("v") + ".")


# --- Go ------------------------------------------------------------------------------


async def _install_go(selector: str) -> str:
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if arch is None:
        raise WorkflowError(f"No Go build for this machine ({platform.machine()})")
    releases = await _get_json("https://go.dev/dl/?mode=json&include=all")
    release = next((r for r in releases if _go_matches(r, selector)), None)
    if release is None:
        raise WorkflowError(f"No Go release matches {selector!r}")
    file = next(
        (f for f in release["files"] if f["os"] == "linux" and f["arch"] == arch and f["kind"] == "archive"), None
    )
    if file is None:
        raise WorkflowError(f"No Go {release['version']} archive for linux/{arch}")
    target = settings.toolchains_dir / release["version"]  # e.g. go1.22.3, holding go/
    if not (target / "go" / "bin" / "go").exists():
        await _download_and_extract(f"https://go.dev/dl/{file['filename']}", file["sha256"], target)
    _link(target / "go" / "bin", ["go", "gofmt"])
    return f"Go {release['version'].removeprefix('go')} installed for the whole team (go, gofmt)."


def _go_matches(release: dict, selector: str) -> bool:
    version = release["version"].removeprefix("go")
    if selector == "stable":
        return release.get("stable", False)
    return release.get("stable", False) and (version == selector or version.startswith(selector + "."))


# --- Python --------------------------------------------------------------------------


def venv_dir() -> Path:
    return settings.toolchains_dir / "python-venv"


async def _install_python(packages: list[str]) -> str:
    bad = next((p for p in packages if not PACKAGE_RE.match(p)), None)
    if bad is not None:
        raise WorkflowError(f"Invalid package: {bad!r} (a PyPI name with an optional version, e.g. pytest==8.2.0)")
    venv = venv_dir()
    if venv.exists() and not (_venv_matches_python(venv) and await asyncio.to_thread(_venv_is_private, venv)):
        # Base image upgrade (dead or other-minor python), or a venv agents could write in:
        # the server runs its python on every install, so only the server may own it
        try:
            await asyncio.to_thread(shutil.rmtree, venv)
        except OSError as exc:
            raise WorkflowError(f"Cannot reset the Python venv ({exc}): ask the boss to delete {venv}") from exc
    if not (venv / "bin" / "python").exists():
        # The image's packages (the backend's) stay visible: pytest of the backend needs them
        await _run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)])
        # Files copied with their source's mode (e.g. from a shared tool cache) may be group-writable
        await asyncio.to_thread(_make_private, venv)
    if packages:
        await _run([str(venv / "bin" / "python"), "-I", "-m", "pip", "install", "--no-input", "--only-binary=:all:", *packages])
    # A symlink to the venv's python would lose the venv: wrappers keep it
    bin_dir().mkdir(parents=True, exist_ok=True, mode=0o755)
    for command in ("python", "python3", "pip"):
        wrapper = bin_dir() / command
        wrapper.unlink(missing_ok=True)
        target = venv / "bin" / ("python" if command != "pip" else "pip")
        wrapper.write_text(f'#!/bin/sh\nexec "{target}" "$@"\n')
        wrapper.chmod(0o755)
    # Commands of the installed packages (pytest...) have the venv's python in their shebang
    skip = {"python", "python3", "pip", "pip3"}
    _link(venv / "bin", [p.name for p in sorted((venv / "bin").iterdir()) if p.name not in skip
                         and not p.name.startswith(("python", "activate", "Activate"))])
    have = ", ".join(_venv_packages(venv)) or "none"
    return f"Python venv ready for the whole team (python, pip). Packages in the venv: {have}."


def _venv_matches_python(venv: Path) -> bool:
    cfg = venv / "pyvenv.cfg"
    if not cfg.is_file() or not (venv / "bin" / "python").exists():
        return False
    line = next((x for x in cfg.read_text().splitlines() if x.startswith("version")), "")
    return line.split("=")[-1].strip().startswith(f"{sys.version_info.major}.{sys.version_info.minor}.")


def _make_private(venv: Path) -> None:
    for path in [venv, *venv.rglob("*")]:
        if not path.is_symlink() and path.lstat().st_mode & 0o022:
            path.chmod(path.lstat().st_mode & ~0o022)


def _venv_is_private(venv: Path) -> bool:
    """Nothing in the venv is writable by the group or others, or owned by someone else."""
    for path in [venv, *venv.rglob("*")]:
        info = path.lstat()
        if info.st_uid != os.getuid() or (not path.is_symlink() and info.st_mode & 0o022):
            return False
    return True


def _venv_packages(venv: Path) -> list[str]:
    """name==version read from the metadata only."""
    from importlib.metadata import distributions

    site = [str(p) for p in venv.glob("lib/python*/site-packages")]
    return sorted(f"{d.metadata['Name']}=={d.version}" for d in distributions(path=site))


async def _run(cmd: list[str]) -> None:
    # No pip cache (agents could plant a wheel in it) and a umask that keeps the venv
    # server-only: the server runs the venv's python here, agents must not be able to alter it
    env = {"PATH": os.defpath, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_CACHE_DIR": "1", "HOME": "/nonexistent"}
    # subprocess.run in a thread: uvloop's create_subprocess_exec rejects umask
    try:
        proc = await asyncio.to_thread(
            subprocess.run, cmd, env=env, umask=0o022, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600
        )
    except subprocess.TimeoutExpired:
        raise WorkflowError("Python install timed out") from None
    out = proc.stdout
    if proc.returncode:
        raise WorkflowError(f"Python install failed: {out.decode(errors='replace')[-1500:]}")


# --- Helpers -------------------------------------------------------------------------


async def _get_json(url: str):
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def _get_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def _download_and_extract(url: str, sha256: str, into: Path) -> None:
    settings.toolchains_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=settings.toolchains_dir, suffix=".download") as tmp:
        digest = hashlib.sha256()
        async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(1 << 20):
                    digest.update(chunk)
                    tmp.write(chunk)
        tmp.flush()
        if digest.hexdigest() != sha256.lower():
            raise WorkflowError(f"Checksum mismatch for {url}: download refused")
        into.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_extract, Path(tmp.name), into)


def _extract(archive: Path, into: Path) -> None:
    with tarfile.open(archive) as tar:
        tar.extractall(into, filter="data")


def _link(source_bin: Path, commands: list[str]) -> None:
    """Point the team's commands at this version (replacing the previous one)."""
    bin_dir().mkdir(parents=True, exist_ok=True)
    for command in commands:
        target = source_bin / command
        if not target.exists():
            continue
        link = bin_dir() / command
        link.unlink(missing_ok=True)
        link.symlink_to(target)
