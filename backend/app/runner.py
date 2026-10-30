"""Launches one agent run: `claude -p`, billed on the subscription of the employee's account."""

import asyncio
import json
import logging
import os
import pwd
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app import agent_pool, claude_store, toolchains
from app.credits import UsageLimit, parse_usage_limit
from app.mcp_server import run_tokens
from app.mcp_server.server import SERVER_NAME

log = logging.getLogger(__name__)

# Only these variables reach the agent: no database URL, GitHub token, API key, or the
# other accounts' tokens (its own is added as CLAUDE_CODE_OAUTH_TOKEN).
ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "TZ", "TMPDIR",
    "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER",
)  # fmt: skip
# Part of the allowlist that is the backend's own (its home, its user, its PATH): with
# AGENT_USER they are replaced by the agent's, never inherited
BACKEND_OWN = ("PATH", "HOME", "USER", "SHELL", "TMPDIR")
AGENT_PATH = "/usr/local/bin:/usr/bin:/bin"


class ClaudeRunError(RuntimeError):
    pass


class UsageLimitReached(ClaudeRunError):
    """The account ran out of credits or hit its usage limit: not a failure of the run."""

    def __init__(self, limit: UsageLimit) -> None:
        super().__init__("Claude usage limit reached")
        self.limit = limit


class SessionNotFound(ClaudeRunError):
    """--resume pointed to a session claude no longer has."""


@dataclass
class RunSpec:
    author_name: str
    system_prompt: str
    prompt: str
    cwd: Path
    employee_id: int
    # Scope headers (task or conversation); the Authorization header is issued per run
    mcp_headers: dict[str, str]
    mcp_tools: list[str]
    claude_tools: list[str]
    model: str
    # Token of the Claude account the employee runs on
    oauth_token: str | None = None
    max_turns: int | None = None
    resume_session_id: str | None = None


@dataclass
class RunResult:
    session_id: str
    text: str
    is_error: bool
    num_turns: int | None
    cost_usd: float | None
    # From claude's `usage`; None when the output has no such field
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None


def _agent_account(user: str) -> pwd.struct_passwd:
    try:
        return pwd.getpwnam(user)
    except KeyError:
        raise ClaudeRunError(f"Agent user {user!r} does not exist on this machine (AGENT_USER / AGENT_POOL_SIZE)") from None


def _env(author_name: str, oauth_token: str | None, cwd: Path, config_dir: Path | None = None, user: str | None = None, employee_id: int = 0) -> dict[str, str]:
    user = settings.agent_user if user is None else user
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    if config_dir:
        # The run's own throwaway config dir, never the backend's store of sessions
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    if user:
        account = _agent_account(user)
        for key in BACKEND_OWN:
            env.pop(key, None)
        # A pool user gets a fresh HOME per run (inside the run's config dir): what a run writes
        # there (.gitconfig, .npmrc...) must not be executed by the next run on the same uid
        home = str(config_dir / "home") if config_dir and user != settings.agent_user else account.pw_dir
        if config_dir and user != settings.agent_user:
            env["TMPDIR"] = str(config_dir / "tmp")
        env |= {"HOME": home, "USER": account.pw_name, "LOGNAME": account.pw_name, "PATH": AGENT_PATH}
    if not oauth_token:
        raise ClaudeRunError("CLAUDE_CODE_OAUTH_TOKENS is not set (generate a token with `claude setup-token`)")
    env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    # Toolchains the team installed (install_toolchain) come first in PATH
    env["PATH"] = f"{toolchains.bin_dir()}:{env.get('PATH', os.defpath)}"
    env |= toolchains.agent_env(employee_id)
    # Installing a toolchain is an MCP call that takes a while
    env["MCP_TOOL_TIMEOUT"] = "600000"
    # Commits made by the agent are signed with its name
    email = re.sub(r"[^a-z0-9]+", ".", author_name.lower()).strip(".") + "@palabre.local"
    env |= {
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": email,
    }
    # The clone belongs to the backend user: trust this run's clone only. git does not glob
    # safe.directory, so the exact path it is (a subdirectory is covered by its work tree)
    env |= {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": str(cwd.resolve())}
    return env


def _write_mcp_config(headers: dict[str, str], user: str | None = None) -> Path:
    user = settings.agent_user if user is None else user
    # Outside the repositories, so the token can never be committed
    config = {"mcpServers": {SERVER_NAME: {"type": "http", "url": settings.mcp_url, "headers": headers}}}
    if user:
        # The agent must read it, and runtime_dir is closed to it: a directory it can only
        # cross, a name it cannot guess, readable by the run's own group (the user's private
        # group, which the backend belongs to) and nobody else: not the other live runs
        directory = settings.agent_run_dir
        directory.mkdir(mode=0o711, parents=True, exist_ok=True)
        mode = 0o640
    else:
        directory = settings.runtime_dir
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        mode = 0o600
    path = directory / f"mcp-{uuid.uuid4().hex}.json"
    path.touch(mode=mode)
    if user and user != settings.agent_user:
        shutil.chown(path, group=user)
    path.write_text(json.dumps(config))
    return path


async def _claim(paths: list[Path], user: str) -> None:
    """Hand the run's clone and Go cache to its account alone (#160): the others, who could
    plant a hook or a module there for this run to execute, lose their write access.
    With user "palabre" it is the release: the paths go back to the backend."""
    for path in paths:
        path.mkdir(mode=0o770, parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "/usr/local/bin/palabre-claim-clone", str(path), user,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        _, stderr = await proc.communicate()
        if proc.returncode:
            raise ClaudeRunError(f"Cannot hand {path} to {user}: {stderr.decode(errors='replace').strip()}")


def _command(cmd: list[str], env: dict[str, str], user: str | None = None) -> list[str]:
    """Wraps the claude command in sudo when agents run as another user.

    The variables travel in sudo's own environment (not its argv, which `ps` shows);
    `--preserve-env` names the ones sudo lets through, and it resets all the others.
    """
    user = settings.agent_user if user is None else user
    if not user:
        return cmd
    # The sudo rule names the binary by its full path
    binary = shutil.which(cmd[0]) or cmd[0]
    names = ",".join(sorted(env))
    return ["sudo", "-n", "-u", user, f"--preserve-env={names}", "--", binary, *cmd[1:]]


async def _terminate(proc: asyncio.subprocess.Process, user: str | None = None) -> None:
    """Kills a run. Under sudo the process is root's: only the agent's group can be signalled."""
    user = settings.agent_user if user is None else user
    if not user:
        proc.kill()
        return
    killer = await asyncio.create_subprocess_exec(
        "sudo", "-n", "-u", user, "/usr/bin/kill", "-KILL", "--", f"-{proc.pid}",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    try:
        await asyncio.wait_for(killer.wait(), 10)
    except TimeoutError:
        killer.kill()


def _usage(usage: object) -> dict[str, int | None]:
    fields = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cache_creation_tokens": "cache_creation_input_tokens",
        "cache_read_tokens": "cache_read_input_tokens",
    }
    usage = usage if isinstance(usage, dict) else {}
    return {k: v if isinstance(v := usage.get(src), int) else None for k, src in fields.items()}


async def run_claude(spec: RunSpec) -> RunResult:
    ids = {}
    for header in ("X-Palabre-Task", "X-Palabre-Conversation"):
        raw = spec.mcp_headers.get(header)
        if raw is not None and not raw.isdigit():
            log.error("Run of employee %s has a non-numeric %s header %r: all its MCP calls will be refused", spec.employee_id, header, raw)
        ids[header] = int(raw) if raw and raw.isdigit() else None
    token = run_tokens.issue(spec.employee_id, ids["X-Palabre-Task"], ids["X-Palabre-Conversation"])
    try:
        # One system user per live run: another run cannot read this one's environment
        async with agent_pool.lease() as user:
            return await _run_claude(spec, token, user)
    finally:
        run_tokens.revoke(token)


async def _run_claude(spec: RunSpec, token: str, user: str) -> RunResult:
    mcp_config = _write_mcp_config(spec.mcp_headers | {"Authorization": f"Bearer {token}"}, user)
    run_tokens.attach_config(token, mcp_config)
    allowed = [f"mcp__{SERVER_NAME}__{t}" for t in spec.mcp_tools] + spec.claude_tools
    cmd = [
        settings.claude_bin,
        "-p", spec.prompt,
        "--output-format", "json",
        "--mcp-config", str(mcp_config),
        "--strict-mcp-config",
        # Only these built-in tools exist for the agent; the others cannot even be asked for
        "--tools", ",".join(spec.claude_tools),
        "--allowedTools", ",".join(allowed),
        "--append-system-prompt", spec.system_prompt,
        "--max-turns", str(spec.max_turns or settings.claude_max_turns),
        "--model", spec.model,
    ]  # fmt: skip
    if spec.resume_session_id:
        cmd += ["--resume", spec.resume_session_id]

    config_dir = None
    # The legacy shared user has no private group: its clones stay the backend's
    pooled = bool(user) and user != settings.agent_user
    owned = [spec.cwd, toolchains.gopath(spec.employee_id)]
    try:
        try:
            if user:
                config_dir = await asyncio.to_thread(claude_store.prepare_run_dir, spec.employee_id, spec.resume_session_id, user)
            if pooled:
                await _claim(owned, user)
            env = _env(spec.author_name, spec.oauth_token, spec.cwd, config_dir, user, spec.employee_id)
            proc = await asyncio.create_subprocess_exec(
                *_command(cmd, env, user),
                cwd=spec.cwd,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Own process group, so the whole run can be killed through the agent
                start_new_session=bool(user),
            )
        except OSError as exc:
            raise ClaudeRunError(f"Cannot start {settings.claude_bin}: {exc}") from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), settings.agent_timeout_s)
        except (TimeoutError, asyncio.CancelledError) as exc:
            await _terminate(proc, user)
            await proc.wait()
            if isinstance(exc, TimeoutError):
                raise ClaudeRunError(f"Timed out after {settings.agent_timeout_s}s") from exc
            raise
    finally:
        mcp_config.unlink(missing_ok=True)
        # Nothing of the run may still write in its dir or clone while they are collected or handed
        # back (a lease's kill comes too late for that). Not for the shared legacy user: it would kill other runs.
        dead = pooled and await agent_pool.kill_all(user)
        if config_dir:
            await claude_store.collect(spec.employee_id, config_dir, user)
        if dead:
            # Back to the backend before the account serves another employee: it could otherwise
            # keep writing a hook in a clone it no longer runs in. Not released if the kill failed
            try:
                await _claim(owned, "palabre")
            except ClaudeRunError:
                log.exception("Cannot take %s back from %s", owned, user)

    try:
        data = json.loads(stdout)
        session_id = data["session_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        error = stderr.decode(errors="replace")[-2000:]
        if limit := parse_usage_limit(error) or parse_usage_limit(stdout.decode(errors="replace")[-2000:]):
            raise UsageLimitReached(limit) from None
        if spec.resume_session_id and "no conversation found" in error.lower():
            raise SessionNotFound(error) from None
        raise ClaudeRunError(f"claude exited with code {proc.returncode}: {error}") from None

    result = RunResult(
        session_id=session_id,
        text=data.get("result") or "",
        is_error=bool(data.get("is_error")),
        num_turns=data.get("num_turns"),
        cost_usd=data.get("total_cost_usd"),
        **_usage(data.get("usage")),
    )
    if result.is_error:
        if limit := parse_usage_limit(result.text):
            raise UsageLimitReached(limit)
        log.warning("%s: run ended with an error: %s", spec.author_name, result.text or data.get("subtype"))
    return result
