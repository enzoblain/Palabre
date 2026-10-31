"""Tests for the per-role claude effort level and the conversation turn limit."""

import json
from pathlib import Path

import pytest

from app import runner
from app.company.team import EFFORT_LEVELS, effort_for, load_catalog
from app.config import Settings


def test_catalog_efforts_are_valid_levels():
    for key, role in load_catalog()["roles"].items():
        assert role.get("effort", "low") in EFFORT_LEVELS, key


@pytest.mark.parametrize("role", ["product_owner", "designer", "scribe"])
def test_light_company_roles_run_at_low_effort(role):
    assert effort_for([role]) == "low"


def test_research_roles_run_at_low_effort():
    research = [k for k, r in load_catalog()["roles"].items() if r["kind"] == "research" and k != "rapporteur"]
    assert research and all(effort_for([k]) == "low" for k in research)


def test_roles_without_effort_keep_claudes_default():
    assert effort_for(["lead"]) is None
    assert effort_for(["dev_backend"]) is None


def test_combined_roles_take_the_highest_effort_or_none():
    assert effort_for(["scribe", "product_owner"]) == "low"
    assert effort_for(["scribe", "lead"]) is None
    assert effort_for([]) is None


def test_turn_limits(monkeypatch):
    monkeypatch.delenv("CLAUDE_MAX_TURNS", raising=False)
    monkeypatch.delenv("CLAUDE_TASK_MAX_TURNS", raising=False)
    s = Settings(_env_file=None)
    assert s.claude_max_turns == 20
    assert s.claude_task_max_turns == 100


@pytest.mark.parametrize("effort", [None, "low"])
async def test_effort_flag_is_passed_only_when_set(monkeypatch, tmp_path, effort):
    seen = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return json.dumps({"session_id": "s", "result": "ok"}).encode(), b""

    async def fake_exec(*args, **kwargs):
        seen.append(args)
        return Proc()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(runner, "_write_mcp_config", lambda *a, **k: tmp_path / "mcp.json")
    monkeypatch.setattr(runner.run_tokens, "attach_config", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_env", lambda *a, **k: {})
    monkeypatch.setattr(runner.settings, "agent_user", "")
    spec = runner.RunSpec(
        author_name="Léa", system_prompt="", prompt="hi", cwd=Path(tmp_path), employee_id=1,
        mcp_headers={}, mcp_tools=[], claude_tools=[], model="sonnet", effort=effort,
    )  # fmt: skip
    await runner._run_claude(spec, "tok", "")
    (args,) = seen
    assert ("--effort" in args) == (effort is not None)
    if effort:
        assert args[args.index("--effort") + 1] == effort


async def test_project_and_local_settings_are_not_loaded(monkeypatch, tmp_path):
    """A .claude/settings.json (hooks) written by an agent in its cwd must not apply to its next run."""
    hooks = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "touch pwned"}]}]}}
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(hooks))
    seen = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return json.dumps({"session_id": "s", "result": "ok"}).encode(), b""

    async def fake_exec(*args, **kwargs):
        seen.append(args)
        return Proc()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(runner, "_write_mcp_config", lambda *a, **k: tmp_path / "mcp.json")
    monkeypatch.setattr(runner.run_tokens, "attach_config", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_env", lambda *a, **k: {})
    monkeypatch.setattr(runner.settings, "agent_user", "")
    spec = runner.RunSpec(
        author_name="Léa", system_prompt="", prompt="hi", cwd=Path(tmp_path), employee_id=1,
        mcp_headers={}, mcp_tools=[], claude_tools=["Write"], model="sonnet",
    )  # fmt: skip
    await runner._run_claude(spec, "tok", "")
    (args,) = seen
    assert args[args.index("--setting-sources") + 1] == runner.SETTING_SOURCES == "user"
