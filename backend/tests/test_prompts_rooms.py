"""Wakeup prompt: the employee's channels and DMs, and the DM/group/decision rules."""

from app.orchestrator.prompts import OPERATING_RULES, rooms_section, wake_prompt


def test_wake_prompt_lists_rooms():
    prompt = wake_prompt(["mention"], [("#general", "team"), ("@Mehdi", "dm")])
    assert "- #general\n" in prompt + "\n"
    assert "- @Mehdi (DM)" in prompt


def test_wake_prompt_without_rooms_is_unchanged():
    assert wake_prompt(["a", "a"]) == "You are being woken up because:\n- a"
    assert rooms_section([]) is None


def test_common_rules_cover_dm_group_and_decisions():
    assert "DM is for an exchange between two people" in OPERATING_RULES
    assert "concerns several people goes in a group" in OPERATING_RULES
    assert "Never decide anything in a DM" in OPERATING_RULES
