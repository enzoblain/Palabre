"""Tests for the lead's reminder to review the team on every boss message and action."""

from app.company.team import generate_team
from app.orchestrator.prompts import team_review_rule

LEAD = ["lead"]


def _lead(team):
    return next(e for e in team.employees if "lead" in e.roles)


def test_lead_rule_lists_members_with_their_role():
    team = generate_team("enterprise", 1)
    rule = team_review_rule(LEAD, team)
    assert "every message from the boss" in rule and "create or assign a task" in rule
    for employee in team.employees:
        assert f"- {employee.name}, {employee.title}:" in rule


def test_other_roles_do_not_get_it():
    assert team_review_rule(["dev_backend"], generate_team("enterprise", 1)) is None


def test_cues_only_cover_roles_present_in_the_team():
    team = generate_team("enterprise", 1)
    assert "Designer" in team_review_rule(LEAD, team) or "UX/UI" in team_review_rule(LEAD, team)
    team.employees = [e for e in team.employees if not {"designer", "security"} & set(e.roles)]
    rule = team_review_rule(LEAD, team)
    assert "screen or user journey" not in rule and "authentication" not in rule
    assert "pull request" in rule
