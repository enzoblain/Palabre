"""run_oneshot: one claude call without tool or MCP, the prompt on stdin (the subprocess is faked)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.config import settings
from app.mcp_server import run_tokens
from app.runner import ClaudeRunError, run_oneshot


@pytest.fixture
def claude(monkeypatch, tmp_path):
    """Fakes the claude process: `claude.stdout` is its output, `claude.hang` makes it never answer."""
    for name, value in {
        "agent_user": "", "agent_pool_size": 0, "agent_run_dir": tmp_path / "run",
        "runtime_dir": tmp_path / "runtime", "claude_store_dir": tmp_path / "store",
    }.items():  # fmt: skip
        monkeypatch.setattr(settings, name, value)
    state = SimpleNamespace(stdout=b"", hang=False, args=None, stdin=None, killed=False, tokens_during_run=[])

    class Proc:
        returncode = 0

        async def communicate(self, input=None):
            state.stdin = input
            state.tokens_during_run = list(run_tokens._active)
            if state.hang:
                await asyncio.sleep(3600)
            return state.stdout, b""

        def kill(self):
            state.killed = True

        async def wait(self):
            return 0

    async def fake_exec(*args, **kwargs):
        state.args = args
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return state


def answer(**fields) -> bytes:
    return json.dumps({"session_id": "s", "is_error": False, **fields}).encode()


async def call(timeout_s: float = 10, token: str | None = "t") -> str:
    return await run_oneshot("Pick roles", system_prompt="sys", model="haiku", oauth_token=token, timeout_s=timeout_s)


async def test_returns_the_answer_with_no_tool_and_the_prompt_on_stdin(claude):
    claude.stdout = answer(result='["qa"]')
    assert await call() == '["qa"]'
    args = list(claude.args)
    assert args[args.index("--tools") + 1] == "" and args[args.index("--model") + 1] == "haiku"
    assert "--mcp-config" not in args and "--strict-mcp-config" in args and "Pick roles" not in args
    assert claude.stdin == b"Pick roles"


async def test_the_run_token_lives_only_during_the_call(claude):
    claude.stdout = answer(result="x")
    await call()
    assert len(claude.tokens_during_run) == 1
    assert not run_tokens._active


@pytest.mark.parametrize("output", [answer(result="overloaded", is_error=True), answer(), b"garbage"])
async def test_a_failed_call_raises(claude, output):
    claude.stdout = output
    with pytest.raises(ClaudeRunError):
        await call()
    assert not run_tokens._active


async def test_timeout_kills_the_process(claude):
    claude.hang = True
    with pytest.raises(ClaudeRunError, match="Timed out"):
        await call(timeout_s=0.05)
    assert claude.killed


async def test_no_token_raises(claude):
    with pytest.raises(ClaudeRunError):
        await call(token=None)
    assert claude.args is None
