"""Roles of an automatic team: the model's choice, its validation and the deterministic fallback (claude call mocked)."""

import asyncio
import json

import pytest

from app.company import team_selection as selection
from app.company.catalog import CODE, load_catalog, team_permission_error
from app.company.team import generate_team_from_roles
from app.runner import ClaudeRunError

SKELETON = list(selection.SKELETON_ROLES)


@pytest.fixture
def oneshot(monkeypatch):
    """Replaces the claude call: `oneshot.answer` is returned, or raised when it is an exception."""
    state = type("State", (), {"answer": "[]", "prompts": []})()

    async def fake(prompt, **kwargs):
        state.prompts.append(prompt)
        if isinstance(state.answer, BaseException):
            raise state.answer
        return state.answer

    monkeypatch.setattr(selection, "run_oneshot", fake)
    return state


def test_fallback_has_the_exact_count_and_code():
    roles = load_catalog()["roles"]
    for seats in (1, 2, 13, 27):
        chosen = selection.fallback_selection(seats)
        assert len(chosen) == seats
        assert any(CODE in roles[key].permissions for key in chosen)
        assert team_permission_error([[k] for k in (*SKELETON, *chosen)], "company") is None


def test_fallback_follows_the_multinational_seat_order():
    assert selection.fallback_selection(3) == ["dev_backend", "dev_backend", "dev_backend"]
    assert selection.fallback_selection(5)[3:] == ["dev_frontend", "dev_frontend"]


async def test_valid_answer_is_used(oneshot):
    oneshot.answer = json.dumps(["dev_frontend", "designer"])
    assert await selection.select_roles("A landing page", 5, "t") == [*SKELETON, "dev_frontend", "designer"]
    assert "A landing page" in oneshot.prompts[0] and "dev_frontend" in oneshot.prompts[0]


async def test_code_fence_is_accepted(oneshot):
    oneshot.answer = '```json\n["dev_frontend"]\n```'
    assert (await selection.select_roles("A site", 4, "t"))[3:] == ["dev_frontend"]


@pytest.mark.parametrize(
    "answer",
    [
        "not json",
        '{"roles": ["dev_backend"]}',
        '["dev_backend", "dev_frontend"]',  # wrong count
        '["not_a_role"]',
        '["lead"]',  # the lead is already placed
        '["research_peer"]',
        "[1]",
        '["designer"]',  # nobody writes code
    ],
)
async def test_invalid_answer_falls_back(oneshot, answer):
    oneshot.answer = answer
    assert await selection.select_roles("A site", 4, "t") == [*SKELETON, *selection.fallback_selection(1)]


@pytest.mark.parametrize("failure", [ClaudeRunError("boom"), RuntimeError("crash")])
async def test_failed_call_falls_back(oneshot, failure):
    oneshot.answer = failure
    assert await selection.select_roles("A site", 6, "t") == [*SKELETON, *selection.fallback_selection(3)]


async def test_a_failed_call_is_attempted_once(oneshot):
    oneshot.answer = "nope"
    await selection.select_roles("A site", 4, "t")
    assert len(oneshot.prompts) == 1


def test_the_team_has_the_chosen_roles_and_the_enterprise_process():
    team = generate_team_from_roles("enterprise", [*SKELETON, "dev_frontend"], seed=1)
    assert [e.roles for e in team.employees] == [[k] for k in (*SKELETON, "dev_frontend")]
    assert team.process == load_catalog()["modes"]["enterprise"]["process"]
    assert len({e.name for e in team.employees}) == 4


def test_personalities_are_drawn_per_seed():
    same = [generate_team_from_roles("enterprise", SKELETON, seed=s) for s in (1, 1)]
    assert same[0].to_dict() == same[1].to_dict()
    assert generate_team_from_roles("enterprise", SKELETON, seed=2).to_dict() != same[0].to_dict()
