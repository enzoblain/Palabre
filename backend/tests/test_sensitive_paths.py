"""Automatic security gate: the changed paths decide, the author's flag only adds."""

import pytest

from app.sensitive_paths import is_sensitive_path, touches_sensitive_paths


@pytest.mark.parametrize("path", [
    "backend/app/runner.py", "backend/app/mcp_server/tools.py", "backend/app/config.py", "backend/Dockerfile",
    "entrypoint.sh", "docker/entrypoint.sh", "etc/sudoers", "etc/sudoers.d/palabre", "backend/requirements.txt",
    "frontend/package.json", "frontend/package-lock.json", "backend/app/mcp_server/auth.py", "Dockerfile.prod",
    "./Dockerfile", "BACKEND/APP/RUNNER.PY", ".env", ".github/workflows/ci.yml",
])
def test_sensitive(path):
    assert is_sensitive_path(path)


@pytest.mark.parametrize("path", ["README.md", "backend/app/workflow.py", "frontend/src/App.tsx", "docs/runner.md"])
def test_not_sensitive(path):
    assert not is_sensitive_path(path)


def test_any_path_is_enough():
    assert touches_sensitive_paths(["README.md", "backend/app/runner.py"])
    assert not touches_sensitive_paths(["README.md", ""])
