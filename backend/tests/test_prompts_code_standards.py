"""Tests for the code standards given to developers and the checklist given to the reviewer."""

from app.company.team import generate_team
from app.models import Project
from app.orchestrator.dispatcher import build_system_prompt
from app.orchestrator.prompts import REASONS, CODE_STANDARDS, CODE_STANDARDS_LIST, REVIEW_CHECKLIST, code_standards_rule


def test_developers_get_the_code_standards():
    for role in ("dev", "dev_backend", "dev_frontend"):
        assert code_standards_rule([role]) == CODE_STANDARDS
    assert "no `any`" in CODE_STANDARDS and "tests" in CODE_STANDARDS


def test_reviewer_gets_the_checklist_that_requires_changes():
    rule = code_standards_rule(["reviewer"])
    assert rule == REVIEW_CHECKLIST
    assert "`changes`" in rule


def test_other_roles_get_nothing():
    assert code_standards_rule(["qa", "lead"]) is None


def _prompt_for(role: str) -> str:
    team = generate_team("enterprise", 1)
    member = next(m for m in team.employees if role in m.roles)
    project = Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1, kind="company")
    return build_system_prompt(team, member, project, "Boss", first_run=False)


def test_standards_come_from_a_single_list():
    for developer_line, reviewer_line in CODE_STANDARDS_LIST:
        assert f"- {developer_line}" in CODE_STANDARDS
        assert f"- {reviewer_line}" in REVIEW_CHECKLIST


def test_assembled_dev_prompt_has_standards_only():
    prompt = _prompt_for("dev_backend")
    assert CODE_STANDARDS in prompt
    assert REVIEW_CHECKLIST not in prompt


def test_assembled_reviewer_prompt_has_checklist_with_changes_verdict():
    prompt = _prompt_for("reviewer")
    assert REVIEW_CHECKLIST in prompt
    assert CODE_STANDARDS not in prompt
    assert "verdict `changes`" in prompt
    assert "changes_requested" not in REVIEW_CHECKLIST


def test_prompts_require_readme_update_in_same_pr():
    assert "update the README in the same PR" in _prompt_for("dev_backend")
    reviewer_prompt = _prompt_for("reviewer")
    assert "README" in reviewer_prompt and "blocking" in reviewer_prompt


def test_qa_reminded_to_report_missing_readme_update():
    reason = REASONS["pr_ready"]
    assert "README" in reason and "report_bug" in reason
