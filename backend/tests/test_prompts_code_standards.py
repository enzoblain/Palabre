"""Tests for the code standards given to developers and the checklist given to the reviewer."""

from app.orchestrator.prompts import CODE_STANDARDS, REVIEW_CHECKLIST, STANDARD_POINTS, code_standards_rule


def test_developers_get_the_code_standards():
    for role in ("dev", "dev_backend", "dev_frontend"):
        assert code_standards_rule([role]) == CODE_STANDARDS
    assert "no `any`" in CODE_STANDARDS and "tests" in CODE_STANDARDS


def test_reviewer_gets_the_checklist_that_requires_changes():
    rule = code_standards_rule(["reviewer"])
    assert rule == REVIEW_CHECKLIST
    assert "`changes`" in rule and "changes_requested" not in rule


def test_both_blocks_render_every_standard_point():
    for block in (CODE_STANDARDS, REVIEW_CHECKLIST):
        assert all(f"- {point}" in block for point in STANDARD_POINTS)


def test_other_roles_get_nothing():
    assert code_standards_rule(["qa", "lead"]) is None
