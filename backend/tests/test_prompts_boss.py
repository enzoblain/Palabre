"""Tests for the rules about messages addressed to the boss."""

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
