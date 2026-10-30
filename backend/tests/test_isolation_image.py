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
    assert "useradd --create-home --uid 1001 --gid work agent" in DOCKERFILE
    # One account per live run, each with a private group the backend also belongs to
    assert 'useradd --create-home --uid $((2000 + i)) --gid work --groups "agent$i" "agent$i"' in DOCKERFILE
    assert 'usermod --append --groups "agent$i" palabre' in DOCKERFILE
    assert "AGENT_POOL_SIZE=${AGENT_POOL_SIZE}" in DOCKERFILE
    assert "useradd --create-home --uid 1000 --groups work palabre" in DOCKERFILE


def test_single_narrow_sudo_rule():
    rules = re.findall(r'"(palabre ALL=[^"]*)"', DOCKERFILE)
    # Only the claude binary, a process-group kill and the clone remover, only as the agent users, never as root
    assert rules == [
        "palabre ALL=($users) NOPASSWD:SETENV: /home/palabre/.local/bin/claude",
        "palabre ALL=($users) NOPASSWD: /usr/bin/kill -KILL -- -[0-9]*",
        "palabre ALL=($users) NOPASSWD: /usr/local/bin/palabre-rm-clone /data/projects/*",
        "palabre ALL=($users) NOPASSWD: /usr/local/bin/palabre-rm-clone /data/run/claude-*",
    ]
    assert 'users="agent$(for i in' in DOCKERFILE
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

    (tmp_path / "admin_token").write_text("a" * 40)
    (tmp_path / "postgres_password").write_text("p@" + "s" * 40)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    s = Settings(_secrets_dir=tmp_path, _env_file=None)
    assert s.admin_token == "a" * 40
    assert s.database_url == "postgresql+asyncpg://palabre:p%40" + "s" * 40 + "@db:5432/palabre"


def test_empty_secrets_fail_fast(tmp_path, monkeypatch):
    from pydantic import ValidationError

    from app import config

    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    (tmp_path / "admin_token").write_text("")
    with pytest.raises(ValidationError):
        config.Settings(_secrets_dir=tmp_path, _env_file=None)
    (tmp_path / "admin_token").write_text("x" * 40)
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
        (tmp_path / name).write_text("" if name == empty else "s3cret" * 8)
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
            (tmp_path / name).write_text("s3cret" * 8)
    with pytest.raises(ValidationError, match=reason) as exc:
        config.Settings(_secrets_dir=tmp_path, _env_file=None)
    assert "s3cret" not in str(exc.value)


@pytest.mark.parametrize("name, env", [("admin_token", "ADMIN_TOKEN"), ("postgres_password", "POSTGRES_PASSWORD")])
def test_short_secret_blocks_startup_without_leaking_it(tmp_path, monkeypatch, name, env):
    from pydantic import ValidationError

    from app import config

    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    monkeypatch.setattr(config, "SECRETS_DIR", tmp_path)
    for other in ("admin_token", "postgres_password"):
        (tmp_path / other).write_text("short-s3cret" if other == name else "o" * 40)
    with pytest.raises(ValidationError, match=f"{env} is too short") as exc:
        config.Settings(_secrets_dir=tmp_path, _env_file=None)
    assert "short-s3cret" not in str(exc.value)


def test_32_character_secrets_are_accepted(tmp_path, monkeypatch):
    from app import config

    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    (tmp_path / "admin_token").write_text("a" * 32)
    (tmp_path / "postgres_password").write_text("b" * 32)
    assert config.Settings(_secrets_dir=tmp_path, _env_file=None).admin_token == "a" * 32


def test_tini_runs_after_the_privilege_drop():
    script = ENTRYPOINT.read_text()
    assert "--init-groups tini -s -- " in script
    assert 'exec tini -s -- "$@"' in script
    assert 'ENTRYPOINT ["docker-entrypoint.sh"]' in (BACKEND / "Dockerfile").read_text()
