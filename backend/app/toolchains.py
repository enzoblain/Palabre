"""Toolchains the agents install for the whole team (install_toolchain), without root.

They live in the /data volume, so they survive restarts and image rebuilds, and their
commands are linked into one directory added to every agent's PATH. Archives come from
the official download sites only, and are checked against their published SHA-256.
"""

import asyncio
import hashlib
import platform
import re
import tarfile
import tempfile
from collections import defaultdict
from pathlib import Path

import httpx

from app.config import settings
from app.services import WorkflowError

TOOLCHAINS = {
    "node": 'Node.js with npm and npx. Version: "lts" (default), "latest", a major ("20") or exact ("20.11.1")',
    "go": 'Go. Version: "stable" (default), a minor ("1.22") or exact ("1.22.3")',
}
VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,30}$")
_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def bin_dir() -> Path:
    return settings.toolchains_dir / "bin"


def agent_env() -> dict[str, str]:
    """Variables the agents' commands need to use the installed toolchains."""
    root = settings.toolchains_dir
    return {
        "GOPATH": str(root / "gopath"),
        "GOMODCACHE": str(root / "gopath" / "pkg" / "mod"),
        # No C compiler in the image: pure Go builds
        "CGO_ENABLED": "0",
    }


def installed() -> dict[str, str]:
    """Command → the file it runs, for what is currently linked."""
    if not bin_dir().is_dir():
        return {}
    return {p.name: str(p.resolve()) for p in sorted(bin_dir().iterdir()) if p.is_symlink()}


async def install(name: str, version: str = "") -> str:
    if name not in TOOLCHAINS:
        raise WorkflowError(f"Unknown toolchain {name!r}: {', '.join(TOOLCHAINS)}")
    if version and not VERSION_RE.match(version):
        raise WorkflowError(f"Invalid version: {version!r}")
    async with _locks[name]:
        try:
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
