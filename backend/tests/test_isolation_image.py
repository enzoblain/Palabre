"""The image's isolation setup (#101): two users, one narrow sudo rule, a safe /data."""

import os
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
    assert 'useradd --create-home --skel /etc/skel-empty --uid $((2000 + i)) --gid "agent$i" --groups work "agent$i"' in DOCKERFILE
    assert 'usermod --append --groups "agent$i" palabre' in DOCKERFILE
    # /home/agentN: empty skel, root-owned, group r-x, nothing for others
    assert "mkdir /etc/skel-empty" in DOCKERFILE
    assert 'chown -R root:"agent$i" "/home/agent$i"' in DOCKERFILE
    assert 'chmod -R g-w,o-rwx "/home/agent$i" && chmod 550 "/home/agent$i"' in DOCKERFILE
    assert "AGENT_POOL_SIZE=${AGENT_POOL_SIZE}" in DOCKERFILE
    assert "useradd --create-home --uid 1000 --groups work palabre" in DOCKERFILE


def test_single_narrow_sudo_rule():
    rules = re.findall(r'"(palabre ALL=[^"]*)"', DOCKERFILE)
    # Only the claude binary, a process-group kill and the clone remover and the clone upload-pack, as the agent users, and root only for the four claim-clone rules below
    assert rules == [
        "palabre ALL=($users) NOPASSWD:SETENV: /home/palabre/.local/bin/claude",
        "palabre ALL=($users) NOPASSWD: /usr/bin/kill -KILL -- -[0-9]*",
        "palabre ALL=($users) NOPASSWD: /usr/local/bin/palabre-rm-clone ${PROJECTS_DIR}/*",
        "palabre ALL=($users) NOPASSWD: /usr/local/bin/palabre-rm-clone /data/run/claude-*",
        # Serves a task clone to the push fetch as its owner (#193)
        "palabre ALL=($users) NOPASSWD: /usr/local/bin/palabre-upload-pack ${PROJECTS_DIR}/*",
        # Hands a clone to an agent account (#160): the script checks both arguments
        "palabre ALL=(root) NOPASSWD: /usr/local/bin/palabre-claim-clone ${PROJECTS_DIR}/* agent*",
        "palabre ALL=(root) NOPASSWD: /usr/local/bin/palabre-claim-clone /data/toolchains/gopath/* agent*",
        # And takes it back once the run's processes are dead
        "palabre ALL=(root) NOPASSWD: /usr/local/bin/palabre-claim-clone ${PROJECTS_DIR}/* palabre",
        "palabre ALL=(root) NOPASSWD: /usr/local/bin/palabre-claim-clone /data/toolchains/gopath/* palabre",
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


def test_entrypoint_uses_the_configured_projects_root():
    script = ENTRYPOINT.read_text()
    assert "/etc/palabre/projects-root.conf" in script
    assert "$DATA/projects" not in script and '"$DATA"/projects' not in script
    assert 'for project in "$PROJECTS"/project-*' in script
    assert 'chmod 2751 "$PROJECTS"' in script


def _entrypoint_guard(tmp_path, root, env_dir):
    """Runs the root-validation block of the entrypoint against a conf holding `root`."""
    text = ENTRYPOINT.read_text()
    block = text[text.index("PROJECTS=$(cat"):text.index("# The next steps run as root")]
    conf = tmp_path / "conf"
    if root is None:
        conf.unlink(missing_ok=True)
    else:
        conf.write_text(root)
    block = block.replace("/etc/palabre/projects-root.conf", str(conf))
    env = {k: v for k, v in os.environ.items() if k != "PROJECTS_DIR"}
    if env_dir is not None:
        env["PROJECTS_DIR"] = env_dir
    return subprocess.run(["sh", "-c", block + "\necho ok $PROJECTS"], env=env, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")
def test_entrypoint_root_guard_fails_closed(tmp_path):
    for root in ("", "/", "relative", "/srv/projects/", "/srv/pro.js"):
        done = _entrypoint_guard(tmp_path, root, None)
        assert done.returncode == 1 and "bad projects root" in done.stderr, root
    done = _entrypoint_guard(tmp_path, None, None)
    assert done.returncode == 1 and "no projects root" in done.stderr
    # Runtime PROJECTS_DIR differing from the image's root: refuse to start
    done = _entrypoint_guard(tmp_path, "/srv/projects", "/data/projects")
    assert done.returncode == 1 and "differs" in done.stderr
    for env_dir in (None, "/srv/projects"):
        done = _entrypoint_guard(tmp_path, "/srv/projects", env_dir)
        assert done.returncode == 0 and done.stdout.strip() == "ok /srv/projects"


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


def test_runs_have_a_private_primary_group_and_no_shared_writable_dir():
    # A clone is group-writable for its run's private group only (#160)
    assert "--gid \"agent$i\" --groups work" in DOCKERFILE
    script = ENTRYPOINT.read_text()
    assert "2775" not in script and "chmod -R g+rwX \"$dir\"" not in script
    assert 'chown -hR palabre:palabre' in script and "chown palabre:work \"$project/$parent\"" in script
    # The per-employee Go caches go back to the backend at every start, like the clones
    gopath = [l for l in script.splitlines() if "toolchains/gopath/employee-*" in l]
    assert gopath and "claim_back" in script.split(gopath[0])[1].split("done")[0]
    # Without a pool the shared agent gets the clones back through group work, not through the backend
    assert "share_back()" in script and "shared_account=1" in script
    assert 'if [ "$shared_account" = 1 ]; then share_back "$1"; else take_back "$1"; fi' in script
    # One rights model for what goes back to palabre: the entrypoint and claim-clone.sh both drop group and others
    take_back = script[script.index("take_back() {") :].split("\n}\n")[0]
    assert "chmod -R u+rwX,go-rwx,ug-s" in take_back and "g+rwX" not in take_back
    assert "chmod -R u+rwX,go-rwx,ug-s" in CLAIM.read_text()


CLAIM = BACKEND / "scripts" / "claim-clone.sh"


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs sh")
@pytest.mark.parametrize("args", [
    ["/data/projects/project-1/desks/employee-1"],  # no account
    ["/data/projects/project-1/desks/employee-1", "root"],
    ["/data/projects/project-1/desks/employee-1", "agent1x"],
    ["/data/projects/project-1/desks/employee-1", "agent"],  # the legacy user's group is shared
    ["/data/projects/project-1/repo", "agent1"],
    ["/data/projects/project-1/worktrees/task-1/../../repo", "agent1"],
    ["/data/projects/project-1/worktrees/task-1\n/etc", "agent1"],
    ["/data/toolchains/gopath/employee-1/pkg", "agent1"],
    ["/etc", "agent1"],
])
def test_claim_clone_refuses_anything_but_a_clone_and_an_agent(args):
    result = subprocess.run(["sh", str(CLAIM), *args], capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
