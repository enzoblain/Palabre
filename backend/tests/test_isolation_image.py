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
    # Only the claude binary, a process-group kill and the clone remover, only as agent, never as root
    assert rules == [
        "palabre ALL=(agent) NOPASSWD:SETENV: /home/palabre/.local/bin/claude",
        "palabre ALL=(agent) NOPASSWD: /usr/bin/kill -KILL -- -[0-9]*",
        "palabre ALL=(agent) NOPASSWD: /usr/local/bin/palabre-rm-clone /data/projects/*",
        "palabre ALL=(agent) NOPASSWD: /usr/local/bin/palabre-rm-clone /data/run/claude-*",
    ]
    assert "AGENT_USER=agent" in DOCKERFILE


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


def test_secrets_are_files_not_environment():
    compose = (BACKEND.parent / "docker-compose.yml").read_text()
    assert "env_file" not in compose.replace("No env_file", "")
    for name in ("admin_token", "github_token", "claude_code_oauth_tokens", "postgres_password"):
        assert f"{name}:\n    environment:" in compose
    assert "DATABASE_URL" not in compose and "POSTGRES_PASSWORD:" not in compose


def test_settings_read_secret_files(tmp_path, monkeypatch):
    from app.config import Settings

    (tmp_path / "admin_token").write_text("a-token")
    (tmp_path / "postgres_password").write_text("p@ss")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    s = Settings(_secrets_dir=tmp_path, _env_file=None)
    assert s.admin_token == "a-token"
    assert s.database_url == "postgresql+asyncpg://palabre:p%40ss@db:5432/palabre"


def test_empty_secrets_fail_fast(tmp_path, monkeypatch):
    from pydantic import ValidationError

    from app import config

    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    (tmp_path / "admin_token").write_text("")
    with pytest.raises(ValidationError):
        config.Settings(_secrets_dir=tmp_path, _env_file=None)
    (tmp_path / "admin_token").write_text("x")
    monkeypatch.setattr(config, "SECRETS_DIR", tmp_path)
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        config.Settings(_secrets_dir=tmp_path, _env_file=None)
    # An explicit URL is kept
    s = config.Settings(_secrets_dir=tmp_path, _env_file=None, database_url="postgresql+asyncpg://u:p@h/d")
    assert s.database_url.endswith("@h/d")


@pytest.mark.parametrize("value", [None, "", "   ", "\n"])
def test_blank_or_missing_admin_token_blocks_startup(tmp_path, monkeypatch, value):
    from pydantic import ValidationError

    from app import config

    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    if value is not None:
        monkeypatch.setenv("ADMIN_TOKEN", value)
    with pytest.raises(ValidationError, match="admin_token"):
        config.Settings(_secrets_dir=tmp_path, _env_file=None)


def test_sudo_keeps_claude_in_sudos_process_group():
    # With use_pty the group kill of a timed-out run would only reach sudo
    assert "!use_pty" in DOCKERFILE and "!secure_path" in DOCKERFILE


@pytest.mark.parametrize("empty, reason", [("admin_token", "ADMIN_TOKEN is blank"), ("postgres_password", "POSTGRES_PASSWORD is empty")])
def test_empty_compose_secret_is_refused_with_its_reason(tmp_path, monkeypatch, empty, reason):
    # What Compose mounts for `ADMIN_TOKEN=` / `POSTGRES_PASSWORD=` in .env: an empty file
    from pydantic import ValidationError

    from app import config

    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setattr(config, "SECRETS_DIR", tmp_path)
    for name in ("admin_token", "postgres_password"):
        (tmp_path / name).write_text("" if name == empty else "s3cret")
    with pytest.raises(ValidationError, match=reason) as exc:
        config.Settings(_secrets_dir=tmp_path, _env_file=None)
    assert "s3cret" not in str(exc.value)


@pytest.mark.parametrize("missing, reason", [("admin_token", "ADMIN_TOKEN is blank"), ("postgres_password", "POSTGRES_PASSWORD is empty or missing")])
def test_absent_compose_secret_is_refused_with_its_reason(tmp_path, monkeypatch, missing, reason):
    # Compose mounts nothing for an empty environment-sourced secret: no file, no env var
    from pydantic import ValidationError

    from app import config

    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setattr(config, "SECRETS_DIR", tmp_path)
    for name in ("admin_token", "postgres_password"):
        if name != missing:
            (tmp_path / name).write_text("s3cret")
    with pytest.raises(ValidationError, match=reason) as exc:
        config.Settings(_secrets_dir=tmp_path, _env_file=None)
    assert "s3cret" not in str(exc.value)
