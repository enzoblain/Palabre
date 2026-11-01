"""Project creation modes (manual / automatic) and the random personality endpoint."""

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.api import catalog
from app.api.errors import ApiError, ErrorCode, api_error, validation_error
from app.api.projects import _check_creation_mode
from app.api.schemas import MemberIn, ProjectIn
from app.company.catalog import MIN_AUTO_TEAM_SIZE, load_catalog
from app.company.team import personality_for, random_personality

LEAD = MemberIn(name="Elise", roles=["lead"])
DEV = MemberIn(name="Mehdi", roles=["backend_dev"])


def _project(**fields) -> ProjectIn:
    return ProjectIn(name="App", repo_url="https://github.com/acme/app", **fields)


def _refused(body: ProjectIn, code: ErrorCode) -> None:
    with pytest.raises(ApiError) as caught:
        _check_creation_mode(body, "company")
    assert caught.value.status_code == 422
    assert caught.value.code == code


def test_manual_accepts_a_team_with_its_mandatory_member():
    _check_creation_mode(_project(creation_mode="manual", employees=[LEAD, DEV]), "company")


def test_manual_refuses_a_team_without_the_mandatory_member():
    _refused(_project(creation_mode="manual", employees=[DEV]), ErrorCode.LEAD_REQUIRED)


def test_manual_refuses_a_missing_team():
    _refused(_project(creation_mode="manual"), ErrorCode.LEAD_REQUIRED)


def test_auto_accepts_the_minimum_team():
    body = _project(creation_mode="auto", description="A CRM", employee_count=MIN_AUTO_TEAM_SIZE)
    _check_creation_mode(body, "company")


def test_auto_refuses_a_team_below_the_minimum():
    body = _project(creation_mode="auto", description="A CRM", employee_count=MIN_AUTO_TEAM_SIZE - 1)
    _refused(body, ErrorCode.TEAM_TOO_SMALL)


def test_auto_refuses_a_missing_count():
    _refused(_project(creation_mode="auto", description="A CRM"), ErrorCode.TEAM_TOO_SMALL)


def test_auto_refuses_a_blank_description():
    _refused(_project(creation_mode="auto", description="  ", employee_count=5), ErrorCode.INVALID_CREATION_MODE)


def test_auto_refuses_a_hand_made_list():
    body = _project(creation_mode="auto", description="A CRM", employee_count=5, employees=[LEAD])
    _refused(body, ErrorCode.INVALID_CREATION_MODE)


def test_creation_modes_are_for_companies():
    body = _project(creation_mode="manual", employees=[LEAD])
    with pytest.raises(ApiError) as caught:
        _check_creation_mode(body, "research")
    assert caught.value.code == ErrorCode.INVALID_CREATION_MODE


def test_no_creation_mode_keeps_the_previous_behavior():
    _check_creation_mode(_project(), "company")


def test_an_unknown_creation_mode_is_a_validation_error():
    with pytest.raises(ValueError):
        _project(creation_mode="other")


def test_random_personality_is_valid_for_the_kind():
    for kind in ("company", "research"):
        pool = personality_for(kind)
        drawn = random_personality(kind)
        assert set(drawn["traits"]) == {a["key"] for a in pool["axes"]}
        assert set(drawn["traits"].values()) <= set(pool["levels"])
        assert drawn["quirks"] and set(drawn["quirks"]) <= set(pool["quirks"])
        assert {k: v in pool["style"][k] for k, v in drawn["style"].items()} == dict.fromkeys(pool["style"], True)


def test_random_personality_is_reproducible_with_a_seed():
    assert random_personality("company", 7) == random_personality("company", 7)


@pytest.fixture
async def client():
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.include_router(catalog.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_endpoint_draws_a_personality_for_a_role(client):
    role = next(k for k, r in load_catalog()["roles"].items() if r.kind == "company")
    response = await client.get(f"/catalog/roles/{role}/random-personality")
    assert response.status_code == 200
    assert set(response.json()) == {"traits", "quirks", "style"}


async def test_endpoint_refuses_an_unknown_role(client):
    response = await client.get("/catalog/roles/nope/random-personality")
    assert response.status_code == 404
    assert response.json()["code"] == ErrorCode.ROLE_NOT_FOUND
