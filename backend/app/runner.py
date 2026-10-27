"""Launches one agent run: `claude -p`, billed on the subscription (CLAUDE_CODE_OAUTH_TOKEN)."""

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.mcp_server.server import SERVER_NAME

log = logging.getLogger(__name__)

# Only these variables reach the agent: no database URL, GitHub token or API key.
ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "TZ", "TMPDIR",
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER",
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
    mcp_headers: dict[str, str]
    mcp_tools: list[str]
    claude_tools: list[str]
    model: str
    resume_session_id: str | None = None


@dataclass
class RunResult:
    session_id: str
    text: str
    is_error: bool
    num_turns: int | None
    cost_usd: float | None


def _env(author_name: str) -> dict[str, str]:
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    if not env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        raise ClaudeRunError("CLAUDE_CODE_OAUTH_TOKEN is not set (generate one with `claude setup-token`)")
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
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    path = settings.runtime_dir / f"mcp-{uuid.uuid4().hex}.json"
    config = {"mcpServers": {SERVER_NAME: {"type": "http", "url": settings.mcp_url, "headers": headers}}}
    path.touch(mode=0o600)
    path.write_text(json.dumps(config))
    return path


async def run_claude(spec: RunSpec) -> RunResult:
    mcp_config = _write_mcp_config(spec.mcp_headers)
    allowed = [f"mcp__{SERVER_NAME}__{t}" for t in spec.mcp_tools] + spec.claude_tools
    cmd = [
        settings.claude_bin,
        "-p", spec.prompt,
        "--output-format", "json",
        "--mcp-config", str(mcp_config),
        "--strict-mcp-config",
        "--allowedTools", ",".join(allowed),
        "--append-system-prompt", spec.system_prompt,
        "--max-turns", str(settings.claude_max_turns),
        "--model", spec.model,
    ]  # fmt: skip
    if spec.resume_session_id:
        cmd += ["--resume", spec.resume_session_id]

    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=spec.cwd,
                env=_env(spec.author_name),
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
    )
    if result.is_error:
        log.warning("%s: run ended with an error: %s", spec.author_name, result.text or data.get("subtype"))
    return result
