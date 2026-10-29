"""The image's isolation setup (#101): two users, one narrow sudo rule, a safe /data."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
DOCKERFILE = (BACKEND / "Dockerfile").read_text()
ENTRYPOINT = BACKEND / "docker-entrypoint.sh"


def test_agent_user_and_shared_group():
    assert "useradd --create-home --uid 1001 --groups work agent" in DOCKERFILE
    assert "useradd --create-home --uid 1000 --groups work palabre" in DOCKERFILE


def test_single_narrow_sudo_rule():
    rules = re.findall(r"'(palabre ALL=[^']*)'", DOCKERFILE)
    # Only the claude binary, only as agent, never as root
    assert rules == ["palabre ALL=(agent) NOPASSWD:SETENV: /home/palabre/.local/bin/claude"]


def test_toolchains_not_in_backend_path():
    env = "\n".join(line for line in DOCKERFILE.splitlines() if "PATH=" in line)
    assert "toolchains" not in env


def test_no_new_privileges_not_set():
    # It would break sudo
    compose = (BACKEND.parent / "docker-compose.yml").read_text()
    assert "no-new-privileges" not in compose


def test_entrypoint_drops_root_and_keeps_secrets_private():
    script = ENTRYPOINT.read_text()
    assert "chmod 700 \"$DATA/runtime\"" in script
    assert "go-rwx" in script  # reference clones
    assert re.search(r"exec setpriv --reuid=palabre .*\"\$@\"", script)
    assert "umask 002" in script


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")
def test_entrypoint_syntax():
    assert subprocess.run(["sh", "-n", str(ENTRYPOINT)], capture_output=True).returncode == 0


def test_entrypoint_does_not_follow_symlinks_as_root():
    script = ENTRYPOINT.read_text()
    assert "real_dir()" in script
    assert '[ ! -L "$1" ]' in script
    # No root chmod/chown -R on a bare glob result: every one is behind real_dir
    assert 'for repo in "$DATA"/projects/project-*/repo' not in script


def test_backend_home_is_traversable_only():
    assert "chmod 711 /home/palabre" in DOCKERFILE
