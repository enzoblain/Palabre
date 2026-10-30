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


def test_rules_tell_the_boss_can_read_dms():
    assert "can also read DMs" in OPERATING_RULES


async def test_rooms_of_eager_loads_members_and_names_dms_after_the_other_person():
    from types import SimpleNamespace

    from app import services
    from app.models import Room

    from .conftest import make_employee

    me, maya = make_employee("Malik", "dev_backend"), make_employee("Maya", "architect")
    me.project_id = 1
    dm = SimpleNamespace(kind="dm", name="x", members=[me, maya])
    team = SimpleNamespace(kind="team", name="general", members=[])
    seen = []

    class S:
        async def scalars(self, query):
            seen.append(query)
            return SimpleNamespace(all=lambda: [team, dm])

    assert await services.rooms_of(S(), me) == [("#general", "team"), ("@Maya", "dm")]
    assert Room.members.property.key in str(seen[0]._with_options[0].path)
