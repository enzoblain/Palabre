"""Tests for the rules about messages addressed to the boss."""

from app.company.team import generate_team
from app.mcp_server import tools
from app.models import Project
from app.orchestrator.dispatcher import build_system_prompt
from app.orchestrator.prompts import language_rule, boss_messages_rule


def test_language_rule_applies_project_language_to_boss_requests():
    rule = language_rule("français")
    assert "Decisions, questions and escalations" in rule
    assert "written in français" in rule
    assert "Never paste a long technical document" in rule


def test_boss_messages_rule_is_plain_and_in_project_language():
    rule = boss_messages_rule("français")
    assert "direction" in rule
    assert "français" in rule
    assert "short sentences" in rule
    assert "no code references" in rule.lower()
    assert "task or PR numbers" in rule


def test_boss_requests_rule_points_to_the_messages_rule():
    assert "Messages to the boss" in language_rule("français")


def _prompt_for(role: str) -> str:
    team = generate_team("enterprise", 1)
    member = next(m for m in team.employees if role in m.roles)
    project = Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1, kind="company")
    return build_system_prompt(team, member, project, "Boss", first_run=False)


def test_assembled_lead_prompt_has_the_direction_rule():
    prompt = _prompt_for("lead")
    assert "## Messages to the boss" in prompt
    assert "## Requests to the boss" in prompt


def test_assembled_developer_prompt_has_both_boss_rules():
    prompt = _prompt_for("dev_backend")
    assert "## Requests to the boss" in prompt
    assert "## Messages to the boss" in prompt


def test_boss_facing_tools_ask_for_plain_text_without_code_references():
    for tool in (tools.add_decision, tools.escalate, tools.ask_ceo, tools.propose_release):
        doc = " ".join((tool.__doc__ or "").split())
        assert "no code references" in doc, tool.__name__
