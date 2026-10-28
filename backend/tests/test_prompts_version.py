"""Tests for the SemVer rule given to the roles that choose version numbers."""

from app.orchestrator.prompts import VERSION_RULE, version_rule


def test_lead_and_devops_get_the_version_rule():
    assert version_rule(["lead"]) == VERSION_RULE
    assert version_rule(["dev", "devops"]) == VERSION_RULE


def test_other_roles_do_not():
    assert version_rule(["dev_backend", "qa"]) is None
