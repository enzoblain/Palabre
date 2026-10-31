"""Tests for the rules about messages addressed to the boss."""

from app.company.team import generate_team
from app.models import Project
from app.orchestrator.dispatcher import build_system_prompt
from app.orchestrator.prompts import language_rule, lead_boss_rule


def test_language_rule_applies_project_language_to_boss_requests():
    rule = language_rule("français")
    assert "Decisions, questions and escalations" in rule
    assert "written in français" in rule
    assert "Never paste a long technical document" in rule


def test_lead_gets_short_simple_direction_messages_in_project_language():
    rule = lead_boss_rule(["lead"], "français")
    assert rule is not None
    assert "direction" in rule
    assert "français" in rule
    assert "short sentences" in rule
    assert "no code references" in rule.lower()


def test_other_roles_do_not_get_the_lead_rule():
    assert lead_boss_rule(["dev_backend"], "français") is None


def _prompt_for(role: str) -> str:
    team = generate_team("enterprise", 1)
    member = next(m for m in team.employees if role in m.roles)
    project = Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1, kind="company")
    return build_system_prompt(team, member, project, "Boss", first_run=False)


def test_assembled_lead_prompt_has_the_direction_rule():
    prompt = _prompt_for("lead")
    assert "## Messages to the boss" in prompt
    assert "## Requests to the boss" in prompt


def test_assembled_developer_prompt_has_boss_requests_but_not_the_lead_rule():
    prompt = _prompt_for("dev_backend")
    assert "## Requests to the boss" in prompt
    assert "## Messages to the boss" not in prompt
