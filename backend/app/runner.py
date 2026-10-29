"""Launches one agent run: `claude -p`, billed on the subscription of the employee's account."""

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app import toolchains
from app.mcp_server import run_tokens
from app.mcp_server.server import SERVER_NAME

log = logging.getLogger(__name__)

# Only these variables reach the agent: no database URL, GitHub token, API key, or the
# other accounts' tokens (its own is added as CLAUDE_CODE_OAUTH_TOKEN).
ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "TZ", "TMPDIR",
    "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER",
)  # fmt: skip


class ClaudeRunError(RuntimeError):
    pass


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


def _env(author_name: str, oauth_token: str | None) -> dict[str, str]:
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    if not oauth_token:
        raise ClaudeRunError("CLAUDE_CODE_OAUTH_TOKENS is not set (generate a token with `claude setup-token`)")
    env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    # Toolchains the team installed (install_toolchain) come first in PATH
    env["PATH"] = f"{toolchains.bin_dir()}:{env.get('PATH', os.defpath)}"
    env |= toolchains.agent_env()
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
    return env


def _write_mcp_config(headers: dict[str, str]) -> Path:
    # Outside the repositories, so the token can never be committed
    settings.runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = settings.runtime_dir / f"mcp-{uuid.uuid4().hex}.json"
    config = {"mcpServers": {SERVER_NAME: {"type": "http", "url": settings.mcp_url, "headers": headers}}}
    path.touch(mode=0o600)
    path.write_text(json.dumps(config))
    return path


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
    token = run_tokens.issue(spec.employee_id)
    try:
        return await _run_claude(spec, token)
    finally:
        run_tokens.revoke(token)


async def _run_claude(spec: RunSpec, token: str) -> RunResult:
    mcp_config = _write_mcp_config(spec.mcp_headers | {"Authorization": f"Bearer {token}"})
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

    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=spec.cwd,
                env=_env(spec.author_name, spec.oauth_token),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise ClaudeRunError(f"Cannot start {settings.claude_bin}: {exc}") from exc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), settings.agent_timeout_s)
        except (TimeoutError, asyncio.CancelledError) as exc:
            proc.kill()
            await proc.wait()
            if isinstance(exc, TimeoutError):
                raise ClaudeRunError(f"Timed out after {settings.agent_timeout_s}s") from exc
            raise
    finally:
        mcp_config.unlink(missing_ok=True)

    try:
        data = json.loads(stdout)
        session_id = data["session_id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        error = stderr.decode(errors="replace")[-2000:]
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
        log.warning("%s: run ended with an error: %s", spec.author_name, result.text or data.get("subtype"))
    return result
