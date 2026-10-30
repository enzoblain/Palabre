"""Paths whose change always goes through the security gate, whatever the author declares."""

from pathlib import PurePosixPath

# Exact file names, wherever they sit in the tree
SENSITIVE_NAMES = {
    # Dependency manifests and lockfiles
    "requirements.txt", "requirements.in", "requirements-dev.txt", "requirements-dev.in", "pyproject.toml", "poetry.lock", "uv.lock", "pipfile", "pipfile.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
    "cargo.toml", "cargo.lock", "go.mod", "go.sum", "gemfile", "gemfile.lock", "composer.json", "composer.lock",
    # Container, entrypoint, privileges, secrets
    "dockerfile", "entrypoint.sh", "docker-entrypoint.sh", "sudoers", ".env",
    # Settings and agent runner
    "config.py", "runner.py", "auth.py",
}
# Directory prefixes (relative to the repository root)
SENSITIVE_DIRS = ("backend/app/mcp_server/", "mcp_server/", "sudoers.d/", ".github/workflows/")


def is_sensitive_path(path: str) -> bool:
    p = PurePosixPath(path.strip().lower().removeprefix("./"))
    name = p.name
    if name in SENSITIVE_NAMES or name.startswith("dockerfile.") or name.endswith(".dockerfile"):
        return True
    if name.startswith(".env.") or name.endswith((".pem", ".key")):
        return True
    posix = p.as_posix()
    return any(f"/{d}" in f"/{posix}" for d in SENSITIVE_DIRS)


def touches_sensitive_paths(paths: list[str]) -> bool:
    return any(is_sensitive_path(p) for p in paths if p.strip())
