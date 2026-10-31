"""Automatic security gate: the changed paths decide, the author's flag only adds."""

import pytest

from app.sensitive_paths import is_sensitive_path, touches_sensitive_paths


@pytest.mark.parametrize("path", [
    "backend/app/runner.py", "backend/app/mcp_server/tools.py", "backend/app/config.py", "backend/Dockerfile",
    "entrypoint.sh", "docker/entrypoint.sh", "etc/sudoers", "etc/sudoers.d/palabre", "backend/requirements.txt",
    "frontend/package.json", "frontend/package-lock.json", "backend/app/mcp_server/auth.py", "Dockerfile.prod",
    "./Dockerfile", "BACKEND/APP/RUNNER.PY", ".env", ".github/workflows/ci.yml",
    "backend/app/sensitive_paths.py", "backend/app/workflow.py", "backend/app/company/catalog.toml",
    "frontend/nginx.conf", "frontend/src/api.ts", "frontend/src-tauri/tauri.conf.json", "backend/app/toolchains.py",
    "CLAUDE.md", "claude.md", "./Claude.MD", ".github/CODEOWNERS", ".github/dependabot.yml", "docker-compose.override.yml", "compose.yaml",
])
def test_sensitive(path):
    assert is_sensitive_path(path)


@pytest.mark.parametrize("path", ["README.md", "backend/app/services.py", "frontend/src/App.tsx", "docs/runner.md"])
def test_not_sensitive(path):
    assert not is_sensitive_path(path)


def test_any_path_is_enough():
    assert touches_sensitive_paths(["README.md", "backend/app/runner.py"])
    assert not touches_sensitive_paths(["README.md", ""])


def test_moved_file_lists_both_sides():
    assert touches_sensitive_paths(["backend/app/tools.py", "backend/app/mcp_server/tools.py"])


def test_scripts_and_non_ascii():
    assert is_sensitive_path("backend/scripts/rm-clone.sh")
    assert not is_sensitive_path("backend/é.py")


@pytest.mark.parametrize("path", [
    "backend/app/company/catalog/company/roles/qa.toml", "backend/app/company/catalog/research/roles/new_angle.toml",
    "backend/app/mcp_server/permissions.py",
])
def test_role_files_and_permissions_are_sensitive_by_path(path):
    assert is_sensitive_path(path)
